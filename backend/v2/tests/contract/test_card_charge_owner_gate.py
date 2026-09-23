"""Card charges are owner-only below the route, on a real MongoDB (#928).

Staff tiers (roadmap 2026-09-22 section 6, decision 2): card charges move
money, so they are owner-only. The routes use ``require_owner``; this pins the
same rule on the ``compose_admin`` closures the routes call
(``charge_invoice_as_admin_action`` for "Charge card now" on an invoice,
``charge_billing_setup_balance`` for the Family "Fix something" confirm), with
the production ``MongoIdempotencyStore`` and billing repos on a real ``mongod``
with every migration applied (``real_db``), so a caller that bypasses the
route still cannot charge:

* the owner's charge goes through: one PaymentIntent, invoice paid;
* an admin without ``owner`` is refused before anything is written: no
  PaymentIntent, no idempotency plan, no audit entry, invoice untouched;
* the owner of ANOTHER academy is refused and learns nothing: no PaymentIntent
  and academy A's invoice untouched (owner is academy-scoped, and every read
  is academy-scoped).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.application.charge_admin_invoice import ChargeRequiresOwner
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-charge-a"
OTHER = "acad-charge-b"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TOTAL = 5_000
PARENT = "parent-charge-1"
INVOICE = "inv-charge-1"
OWNER = ("admin", "owner")
ADMIN_ONLY = ("admin",)


class _FakeOutbox:
    async def append(self, event: object) -> None:
        return None


class _SavedCardStripe(FakeStripeGateway):
    async def get_default_payment_method(self, *, academy_id: str, parent_id: str):
        return f"cus-{parent_id}", f"pm-{parent_id}"


@pytest.fixture
def boot_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", ACAD)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", ACAD)
    get_settings.cache_clear()
    yield ACAD
    get_settings.cache_clear()


def _admin(db: Any, stripe: FakeStripeGateway) -> Any:
    return compose_admin(
        db,
        outbox=_FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=stripe,
    )


async def _seed_chargeable_invoice(db: Any) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": ACAD,
            "parent_id": PARENT,
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["academy_connected_accounts"].insert_one(
        {
            "academy_id": ACAD,
            "stripe_account_id": "acct-charge-ready",
            "status": "active",
            "capabilities": {},
            "charges_enabled": True,
            "payouts_enabled": True,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enroll-charge-1",
            "parent_id": PARENT,
            "student_id": "student-charge-1",
            "session_type_id": "session-type-1",
            "billing_start_date": NOW,
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )
    await db["invoices"].insert_one(
        {
            "invoice_id": INVOICE,
            "academy_id": ACAD,
            "parent_id": PARENT,
            "student_id": "student-charge-1",
            "enrollment_id": "enroll-charge-1",
            "period": "2026-09",
            "status": "open",
            "subtotal_cents": TOTAL,
            "discount_cents": 0,
            "total_cents": TOTAL,
            "balance_due_cents": TOTAL,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 9, 30, tzinfo=UTC),
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def _setup_charge(admin: Any, roles: tuple[str, ...], request_id: str) -> Any:
    return admin.charge_billing_setup_balance(
        parent_id=PARENT,
        invoice_id=INVOICE,
        expected_amount_cents=TOTAL,
        request_id=request_id,
        actor_id="staff-charge-1",
        actor_roles=roles,
    )


def _invoice_charge(admin: Any, roles: tuple[str, ...], request_id: str) -> Any:
    return admin.charge_invoice_as_admin_action(
        invoice_id=INVOICE,
        actor_id="staff-charge-1",
        actor_roles=roles,
        reason="family asked",
        request_id=request_id,
    )


_ENTRIES = {"billing-setup": _setup_charge, "invoice": _invoice_charge}


async def _untouched(db: Any, stripe: FakeStripeGateway) -> None:
    assert stripe.off_session_payment_intents == []
    invoice = await db["invoices"].find_one({"academy_id": ACAD, "invoice_id": INVOICE})
    assert invoice is not None
    assert invoice["status"] == "open"
    assert invoice["balance_due_cents"] == TOTAL
    assert await db["ledger_payments"].count_documents({}) == 0
    assert await db["billing_audit_log"].count_documents({}) == 0
    assert await db["idempotency_keys"].count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", list(_ENTRIES), ids=list(_ENTRIES))
async def test_owner_can_charge_the_card(real_db: Any, boot_academy: str, entry: str) -> None:
    await _seed_chargeable_invoice(real_db)
    stripe = _SavedCardStripe()
    admin = _admin(real_db, stripe)

    with tenant_scope(ACAD):
        result = await _ENTRIES[entry](admin, OWNER, f"owner-{entry}-request-0001")

    assert result["success"] is True
    assert len(stripe.off_session_payment_intents) == 1
    invoice = await real_db["invoices"].find_one({"academy_id": ACAD, "invoice_id": INVOICE})
    assert invoice is not None and invoice["balance_due_cents"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", list(_ENTRIES), ids=list(_ENTRIES))
async def test_admin_without_owner_is_refused_and_nothing_moves(
    real_db: Any, boot_academy: str, entry: str
) -> None:
    await _seed_chargeable_invoice(real_db)
    stripe = _SavedCardStripe()
    admin = _admin(real_db, stripe)

    with tenant_scope(ACAD), pytest.raises(ChargeRequiresOwner):
        await _ENTRIES[entry](admin, ADMIN_ONLY, f"admin-{entry}-request-0001")

    await _untouched(real_db, stripe)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", list(_ENTRIES), ids=list(_ENTRIES))
async def test_owner_of_another_academy_cannot_charge_this_academys_card(
    real_db: Any, boot_academy: str, entry: str
) -> None:
    await _seed_chargeable_invoice(real_db)
    stripe = _SavedCardStripe()
    admin = _admin(real_db, stripe)

    with tenant_scope(OTHER), pytest.raises(ValueError) as refused:
        await _ENTRIES[entry](admin, OWNER, f"other-{entry}-request-0001")

    # Refused as "not here", never as a hint about academy A's invoice.
    assert str(refused.value).split(":", 1)[0] in {
        f"invoice {INVOICE!r} not found",
        "no_saved_payment_method",
        "charge_target_changed",
    }
    await _untouched(real_db, stripe)
