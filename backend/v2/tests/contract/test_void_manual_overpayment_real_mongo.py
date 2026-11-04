"""Voiding a mistaken manual overpayment, end to end on a real MongoDB.

The case that motivated it: a $300 Zelle was recorded against one $60 invoice
with nothing else open, so $60 settled the invoice and the other $240 became
an OVERPAYMENT account credit. Undoing it must void the PAYMENT, not the
invoice: the invoice stays and reopens, the credit the payment minted is
cancelled, and the payment row survives as ``voided`` with a
``payment_voided`` audit entry.

Once any of that credit has paid another invoice, voiding would cancel the
credit but could not take back what it paid, so the void is refused before
any write.

Runs through the real ``compose_admin`` closures on ``real_db`` (every
migration applied), so the indexes and validators are production's.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-void-overpay"
PARENT = "parent-void-1"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class _FakeOutbox:
    async def append(self, event: object) -> None:
        return None


@pytest.fixture
def boot_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    yield ACAD
    get_settings.cache_clear()


def _admin(db: Any) -> Any:
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _seed_invoice(db: Any, invoice_id: str, period: str, total_cents: int = 6_000) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": invoice_id,
            "academy_id": ACAD,
            "parent_id": PARENT,
            "student_id": "student-void-1",
            "enrollment_id": "enroll-void-1",
            "period": period,
            "status": "open",
            "subtotal_cents": total_cents,
            "discount_cents": 0,
            "total_cents": total_cents,
            "balance_due_cents": total_cents,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 10, 31, tzinfo=UTC),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


async def _record_300_zelle(admin: Any) -> None:
    await admin.record_manual_payment(
        invoice_id="inv-oct",
        amount_cents=30_000,
        payment_method="zelle",
        reference_number=None,
        notes="",
        actor_id="owner-1",
        idempotency_key="zelle-300",
    )


async def _the_payment(db: Any) -> dict[str, Any]:
    payment = await db["ledger_payments"].find_one({"academy_id": ACAD})
    assert payment is not None
    return payment


async def _the_credit(db: Any) -> dict[str, Any]:
    credit = await db["account_credit_ledger"].find_one(
        {"academy_id": ACAD, "source_type": "OVERPAYMENT"}
    )
    assert credit is not None
    return credit


@pytest.mark.asyncio
async def test_void_reopens_the_invoice_cancels_the_credit_and_keeps_the_payment(
    real_db, boot_academy
) -> None:
    await _seed_invoice(real_db, "inv-oct", "2026-10")
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await _record_300_zelle(admin)
        payment = await _the_payment(real_db)
        credit = await _the_credit(real_db)
        invoice = await real_db["invoices"].find_one({"invoice_id": "inv-oct"})
        assert invoice["status"] == "paid"
        assert credit["amount_cents"] == 24_000
        assert credit["remaining_amount_cents"] == 24_000

        await admin.void_payment(
            payment_id=payment["payment_id"],
            reason="entered on the wrong invoice",
            actor_id="owner-1",
        )

    invoice = await real_db["invoices"].find_one({"invoice_id": "inv-oct"})
    assert invoice is not None
    assert invoice["status"] == "open"
    assert invoice["balance_due_cents"] == 6_000

    credit = await _the_credit(real_db)
    assert credit["status"] == "VOIDED"
    assert credit["remaining_amount_cents"] == 0

    voided = await _the_payment(real_db)
    assert voided["status"] == "voided"
    assert voided["amount_cents"] == 30_000
    assert voided["void_reason"] == "entered on the wrong invoice"
    assert await real_db["payment_allocations"].count_documents({"academy_id": ACAD}) == 0
    audit = await real_db["billing_audit_log"].find_one(
        {"academy_id": ACAD, "action": "payment_voided"}
    )
    assert audit is not None and audit["payment_id"] == payment["payment_id"]


@pytest.mark.asyncio
async def test_void_is_refused_once_the_minted_credit_paid_another_invoice(
    real_db, boot_academy
) -> None:
    await _seed_invoice(real_db, "inv-oct", "2026-10")
    admin = _admin(real_db)
    with tenant_scope(ACAD):
        await _record_300_zelle(admin)
        # November's invoice arrives later and is paid from the $240 credit.
        await _seed_invoice(real_db, "inv-nov", "2026-11")
        applied = await MongoCreditLedgerRepository(real_db).apply_available_credits(
            parent_id=PARENT, invoice_id="inv-nov", amount_due_cents=6_000
        )
        assert applied == 6_000
        payment = await _the_payment(real_db)

        with pytest.raises(ValueError, match=r"\$60\.00 .* already used"):
            await admin.void_payment(
                payment_id=payment["payment_id"], reason="wrong invoice", actor_id="owner-1"
            )

    # Refused before any write: the payment, its allocation and the credit are untouched.
    assert (await _the_payment(real_db))["status"] != "voided"
    assert (
        await real_db["payment_allocations"].count_documents(
            {"academy_id": ACAD, "payment_id": payment["payment_id"]}
        )
        == 2  # the $60 settlement plus the $0 row the $240 credit hangs off
    )
    credit = await _the_credit(real_db)
    assert credit["status"] != "VOIDED"
    assert credit["remaining_amount_cents"] == 18_000
    invoice = await real_db["invoices"].find_one({"invoice_id": "inv-oct"})
    assert invoice is not None and invoice["status"] == "paid"
