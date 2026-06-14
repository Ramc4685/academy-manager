"""Contract tests: LedgerPayment writes go to ledger_payments, not payments."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import (
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)


def _make_invoice(invoice_id: str, academy_id: str, now: datetime) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id="parent-1",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=now,
        updated_at=now,
    )


def _make_payment(
    payment_id: str, academy_id: str, now: datetime, amount: int = 10_000
) -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id=academy_id,
        parent_id="parent-1",
        amount_cents=amount,
        unapplied_amount_cents=amount,
        currency="usd",
        status="succeeded",
        payment_method="cash",
        paid_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_record_payment_writes_to_ledger_payments(db, acad) -> None:
    """record_payment must write to ledger_payments, not payments."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    payment = _make_payment("pay-storage-1", acad, now)

    result = await repo.record_payment(payment, idempotency_key="pay:storage:1")

    assert result.payment_id == "pay-storage-1"
    # Must appear in ledger_payments
    assert await db["ledger_payments"].count_documents({"payment_id": "pay-storage-1"}) == 1
    # Must NOT appear in legacy payments collection
    assert await db["payments"].count_documents({"payment_id": "pay-storage-1"}) == 0


@pytest.mark.asyncio
async def test_record_payment_idempotency_via_ledger_payments(db, acad) -> None:
    """Idempotent re-record reads from ledger_payments, not payments."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    payment = _make_payment("pay-idem-2", acad, now)

    first = await repo.record_payment(payment, idempotency_key="pay:idem:2")
    second = await repo.record_payment(payment, idempotency_key="pay:idem:2")

    assert first == second
    assert await db["ledger_payments"].count_documents({"payment_id": "pay-idem-2"}) == 1


@pytest.mark.asyncio
async def test_allocate_payment_reads_from_ledger_payments(db, acad) -> None:
    """allocate_payment must find the payment in ledger_payments."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-alloc-3", acad, now)
    payment = _make_payment("pay-alloc-3", acad, now)

    await repo.create_invoice(invoice, lines=[], idempotency_key="inv:alloc:3")
    await repo.record_payment(payment, idempotency_key="pay:alloc:3")

    result = await repo.allocate_payment(
        payment_id="pay-alloc-3",
        invoice_id="inv-alloc-3",
        amount_cents=10_000,
        idempotency_key="alloc:3",
    )

    assert result.payment.payment_id == "pay-alloc-3"
    assert result.invoice.invoice_id == "inv-alloc-3"
    # The updated payment doc must be in ledger_payments
    updated = await db["ledger_payments"].find_one({"payment_id": "pay-alloc-3"})
    assert updated is not None
    assert updated["unapplied_amount_cents"] == 0


@pytest.mark.asyncio
async def test_no_cross_collection_contamination(db, acad) -> None:
    """A payment recorded via record_payment must never appear in payments."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    payment = _make_payment("pay-contamination-4", acad, now)

    await repo.record_payment(payment, idempotency_key="pay:contamination:4")

    # Explicitly confirm the legacy payments collection is untouched
    legacy_count = await db["payments"].count_documents({})
    assert legacy_count == 0, f"Expected 0 docs in payments, got {legacy_count}"
    ledger_count = await db["ledger_payments"].count_documents({})
    assert ledger_count == 1


@pytest.mark.asyncio
async def test_save_get_invoice_strips_mongo_id(db, acad) -> None:
    """save_invoice → get_invoice must not raise ValidationError due to _id or idempotency_key."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-roundtrip-1", acad, now)

    saved = await repo.save_invoice(invoice)

    # Verify the raw Mongo document contains _id (motor/mongomock always adds it)
    raw = await db["invoices"].find_one({"invoice_id": "inv-roundtrip-1"})
    assert raw is not None
    assert "_id" in raw

    # get_invoice must succeed and return a valid LedgerInvoice (no ValidationError)
    fetched = await repo.get_invoice("inv-roundtrip-1")
    assert fetched is not None
    assert fetched.invoice_id == "inv-roundtrip-1"
    assert fetched == saved


@pytest.mark.asyncio
async def test_create_invoice_strips_mongo_id(db, acad) -> None:
    """create_invoice idempotent re-read must not raise ValidationError due to _id/idempotency_key."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-roundtrip-2", acad, now)

    first = await repo.create_invoice(invoice, lines=[], idempotency_key="inv:roundtrip:2")
    # Second call hits the idempotency path — _invoice_from_doc is called on the stored doc
    second = await repo.create_invoice(invoice, lines=[], idempotency_key="inv:roundtrip:2")

    assert first.invoice_id == "inv-roundtrip-2"
    assert first == second


@pytest.mark.asyncio
async def test_list_payments_for_parent(db, acad) -> None:
    """list_payments_for_parent returns payments from ledger_payments only."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)

    await repo.record_payment(
        _make_payment("pay-list-a", acad, now, 5_000), idempotency_key="pay:list:a"
    )
    await repo.record_payment(
        _make_payment("pay-list-b", acad, now, 8_000), idempotency_key="pay:list:b"
    )

    results = await repo.list_payments_for_parent("parent-1")
    ids = {p.payment_id for p in results}

    assert ids == {"pay-list-a", "pay-list-b"}
    # Nothing leaked into legacy collection
    assert await db["payments"].count_documents({}) == 0
