"""Voiding a payment reopens the invoice it settled (#619).

The point of a void is that the money it represented never existed. Flipping
the payment's status alone would leave its ``payment_allocations`` rows in
place, so the invoice would still read as paid with nothing behind it. This
reverses the allocations through the same machinery an ACH return uses —
audit-preserving (a ``payment_allocation_reversals`` row per allocation), and
the payment document itself is never deleted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def _invoice(invoice_id: str, academy_id: str, amount: int = 10_000) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id="parent-619",
        period="2026-09",
        status="open",
        subtotal_cents=amount,
        discount_cents=0,
        total_cents=amount,
        balance_due_cents=amount,
        currency="usd",
        due_date=date(2026, 9, 30),
        created_at=NOW,
        updated_at=NOW,
    )


def _payment(
    payment_id: str, academy_id: str, amount: int = 10_000, **overrides: object
) -> LedgerPayment:
    base: dict[str, object] = {
        "payment_id": payment_id,
        "academy_id": academy_id,
        "parent_id": "parent-619",
        "amount_cents": amount,
        "unapplied_amount_cents": amount,
        "currency": "usd",
        "status": "succeeded",
        "payment_method": "cash",
        "paid_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return LedgerPayment(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_void_payment_reopens_the_invoice_it_paid(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(_invoice("inv-619", acad), lines=[], idempotency_key="inv:619")
    await repo.record_payment(_payment("pay-619", acad), idempotency_key="pay:619")
    await repo.allocate_payment(
        payment_id="pay-619",
        invoice_id="inv-619",
        amount_cents=10_000,
        idempotency_key="alloc:619",
    )
    paid = await db["invoices"].find_one({"invoice_id": "inv-619"})
    assert paid is not None and paid["status"] == "paid"

    voided = await repo.void_payment(
        "pay-619", reason="recorded in error", voided_by="u-owner", now=NOW
    )

    assert voided.status == "voided"
    assert voided.void_reason == "recorded in error"
    assert voided.voided_by == "u-owner"

    invoice = await db["invoices"].find_one({"invoice_id": "inv-619"})
    assert invoice is not None
    assert invoice["balance_due_cents"] == 10_000
    assert invoice["status"] == "open"

    # No hard delete: the payment row survives with its original amount.
    payment_doc = await db["ledger_payments"].find_one({"payment_id": "pay-619"})
    assert payment_doc is not None
    assert payment_doc["status"] == "voided"
    assert payment_doc["amount_cents"] == 10_000
    # ...and holds no money an allocator could still spend.
    assert payment_doc["unapplied_amount_cents"] == 0

    allocations = [doc async for doc in db["payment_allocations"].find({"payment_id": "pay-619"})]
    assert allocations == []
    reversals = [
        doc async for doc in db["payment_allocation_reversals"].find({"payment_id": "pay-619"})
    ]
    assert len(reversals) == 1


@pytest.mark.asyncio
async def test_void_payment_refuses_settled_stripe_money(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await repo.record_payment(
        _payment("pay-619-stripe", acad, stripe_payment_intent_id="pi_live_619"),
        idempotency_key="pay:619:stripe",
    )

    with pytest.raises(ValueError, match="refund"):
        await repo.void_payment("pay-619-stripe", reason="test row", voided_by="u-owner", now=NOW)

    doc = await db["ledger_payments"].find_one({"payment_id": "pay-619-stripe"})
    assert doc is not None and doc["status"] == "succeeded"


@pytest.mark.asyncio
async def test_void_payment_is_idempotent_on_a_voided_row(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    await repo.record_payment(_payment("pay-619-twice", acad), idempotency_key="pay:619:twice")
    await repo.void_payment("pay-619-twice", reason="t", voided_by="u", now=NOW)

    with pytest.raises(ValueError, match="already voided"):
        await repo.void_payment("pay-619-twice", reason="t", voided_by="u", now=NOW)


@pytest.mark.asyncio
async def test_void_payment_raises_for_a_missing_payment(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    with pytest.raises(ValueError, match="not found"):
        await repo.void_payment("pay-619-missing", reason="t", voided_by="u", now=NOW)


def test_every_money_report_allow_list_excludes_voided() -> None:
    """Reports select payments by allow-list, so "voided" is excluded for free.

    That is only true while the lists stay allow-lists. This pins them: adding
    "voided" to any of them (or turning one into a deny-list) puts test payments
    back into revenue, the deposit slip and cash-received — the exact divergence
    between the list and the reports that #619 warns about.
    """
    from backend.v2.contexts.billing.application.admin_payment_settlement import (
        SETTLED_STATUSES,
    )
    from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
        _LEDGER_SUCCESS_STATUSES,
    )
    from backend.v2.contexts.billing.infrastructure.cash_received import (
        SUCCESSFUL_LEDGER_STATUSES,
    )

    for allow_list in (SETTLED_STATUSES, _LEDGER_SUCCESS_STATUSES, SUCCESSFUL_LEDGER_STATUSES):
        assert "voided" not in allow_list
