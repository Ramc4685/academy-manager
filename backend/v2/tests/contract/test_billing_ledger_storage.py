"""Contract tests: LedgerPayment writes go to ledger_payments, not payments."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
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


def _make_payment_with_metadata(payment_id: str, academy_id: str, now: datetime) -> LedgerPayment:
    return _make_payment(payment_id, academy_id, now).model_copy(
        update={
            "stripe_payment_intent_id": "pi_metadata_1",
            "metadata": {"disclosure_version": "cash-discount-v1"},
        }
    )


def _make_line(line_id: str, invoice_id: str, academy_id: str, amount: int) -> InvoiceLine:
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    return InvoiceLine(
        line_id=line_id,
        academy_id=academy_id,
        invoice_id=invoice_id,
        line_type="fee",
        description="Fee",
        quantity=1,
        unit_amount_cents=amount,
        amount_cents=amount,
        created_at=now,
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
async def test_record_payment_round_trips_metadata(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)

    saved = await repo.record_payment(
        _make_payment_with_metadata("pay-metadata-1", acad, now),
        idempotency_key="pay:metadata:1",
    )
    fetched = await repo.get_payment_by_stripe_payment_intent_id(
        saved.stripe_payment_intent_id or ""
    )

    raw = await db["ledger_payments"].find_one({"payment_id": "pay-metadata-1"})
    assert raw is not None
    assert raw["metadata"] == {"disclosure_version": "cash-discount-v1"}
    assert fetched is not None
    assert fetched.metadata == {"disclosure_version": "cash-discount-v1"}


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
async def test_reconciliation_lookup_methods_are_tenant_scoped(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-reconcile-lookup", acad, now)
    payment = _make_payment("pay-reconcile-lookup", acad, now).model_copy(
        update={"stripe_payment_intent_id": "pi_reconcile_lookup"}
    )

    await repo.create_invoice(invoice, lines=[], idempotency_key="inv:reconcile:lookup")
    await repo.record_payment(payment, idempotency_key="pay:reconcile:lookup")
    await repo.allocate_payment(
        payment_id=payment.payment_id,
        invoice_id=invoice.invoice_id,
        amount_cents=10_000,
        idempotency_key="alloc:reconcile:lookup",
    )

    found_payment = await repo.get_payment_by_stripe_payment_intent_id("pi_reconcile_lookup")
    found_allocation = await repo.get_payment_allocation_by_idempotency_key(
        "alloc:reconcile:lookup"
    )

    assert found_payment is not None
    assert found_payment.payment_id == payment.payment_id
    assert found_allocation is not None
    assert found_allocation.invoice_id == invoice.invoice_id


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
async def test_save_invoice_keeps_due_date_as_mongo_date(db, acad) -> None:
    """Validated invoice collections require due_date as a date-like value, not an ISO string."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-due-date-type", acad, now)

    await repo.save_invoice(invoice)

    raw = await db["invoices"].find_one({"invoice_id": "inv-due-date-type"})
    assert raw is not None
    assert isinstance(raw["due_date"], datetime)
    assert not isinstance(raw["due_date"], str)


@pytest.mark.asyncio
async def test_add_invoice_line_repairs_existing_string_due_date(db, acad) -> None:
    """Older seeded invoices with string due_date must not fail validated Mongo updates."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-string-due-date", acad, now)
    raw_invoice = invoice.model_dump(mode="python")
    raw_invoice["due_date"] = "2026-06-30"
    await db["invoices"].insert_one(raw_invoice)
    await repo.save_line(_make_line("line-existing-tuition", invoice.invoice_id, acad, 10_000))

    result = await AddInvoiceLine(ledger=repo, clock=lambda: now).execute(
        AddInvoiceLineCommand(
            invoice_id=invoice.invoice_id,
            description="New racket",
            line_type="equipment",
            quantity=1,
            unit_amount_cents=3_000,
        )
    )

    assert result.invoice.total_cents == 13_000
    raw = await db["invoices"].find_one({"invoice_id": invoice.invoice_id})
    assert raw is not None
    assert isinstance(raw["due_date"], datetime)
    assert not isinstance(raw["due_date"], str)


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


@pytest.mark.asyncio
async def test_delete_invoice_line_is_tenant_scoped_and_reports_missing(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    invoice = _make_invoice("inv-delete-line", acad, now)
    line = _make_line("line-delete", invoice.invoice_id, acad, 4_000)

    await repo.create_invoice(invoice, lines=[line], idempotency_key="inv:delete-line")
    await db["invoice_lines"].insert_one(
        {
            **line.model_dump(mode="python"),
            "academy_id": "other-academy",
        }
    )

    assert (
        await repo.delete_invoice_line(
            invoice_id=invoice.invoice_id,
            line_id="missing-line",
        )
        is False
    )
    assert (
        await repo.delete_invoice_line(
            invoice_id=invoice.invoice_id,
            line_id=line.line_id,
        )
        is True
    )
    assert await db["invoice_lines"].count_documents({"academy_id": acad}) == 0
    assert await db["invoice_lines"].count_documents({"academy_id": "other-academy"}) == 1


@pytest.mark.asyncio
async def test_save_invoice_rejects_stale_concurrent_write(db, acad) -> None:
    """P0-2: two writers read the same invoice version; the second (stale) save is rejected
    so a concurrent add_line cannot silently clobber the first writer's update."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-cc-1", acad, now), lines=[], idempotency_key="cc:1"
    )

    # Two concurrent readers both see version 0.
    reader_a = await repo.get_invoice("inv-cc-1")
    reader_b = await repo.get_invoice("inv-cc-1")
    assert reader_a is not None and reader_b is not None
    assert reader_a.version == 0

    # Writer A commits first and wins (version -> 1).
    saved_a = await repo.save_invoice(reader_a.model_copy(update={"balance_due_cents": 5_000}))
    assert saved_a.version == 1

    # Writer B is stale (still version 0) and must be rejected, not last-write-wins.
    with pytest.raises(ValueError, match="invoice changed"):
        await repo.save_invoice(reader_b.model_copy(update={"balance_due_cents": 3_000}))

    final = await repo.get_invoice("inv-cc-1")
    assert final is not None
    assert final.balance_due_cents == 5_000  # writer A preserved, B did not clobber


@pytest.mark.asyncio
async def test_save_invoice_bumps_version_on_each_write(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-cc-2", acad, now), lines=[], idempotency_key="cc:2"
    )
    v0 = await repo.get_invoice("inv-cc-2")
    assert v0 is not None and v0.version == 0
    v1 = await repo.save_invoice(v0.model_copy(update={"balance_due_cents": 9_000}))
    assert v1.version == 1
    v2 = await repo.save_invoice(v1.model_copy(update={"balance_due_cents": 8_000}))
    assert v2.version == 2


@pytest.mark.asyncio
async def test_manual_payment_overpayment_creates_account_credit(db, acad) -> None:
    """P0-3: a manual payment exceeding the balance must succeed and create an APPROVED
    OVERPAYMENT credit for the remainder (same behavior as the Stripe allocation path),
    instead of being hard-rejected."""
    from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
        RecordManualPayment,
        RecordManualPaymentCommand,
    )

    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-over-1", acad, now), lines=[], idempotency_key="over:1"
    )

    uc = RecordManualPayment(ledger=repo)
    result = await uc.execute(
        RecordManualPaymentCommand(
            invoice_id="inv-over-1", amount_cents=13_000, payment_method="cash"
        )
    )

    assert result.invoice_status == "paid"
    assert result.balance_due_cents == 0
    assert result.overpayment_credit_cents == 3_000
    credits = await db["account_credit_ledger"].count_documents(
        {"academy_id": acad, "source_type": "OVERPAYMENT", "status": "APPROVED"}
    )
    assert credits == 1


@pytest.mark.asyncio
async def test_apply_invoice_refund_is_single_writer(db, acad) -> None:
    """P0-3: refunded_cents is written by exactly one repo method and is the single source
    of truth (model value == persisted doc value), replacing the raw composition $inc."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-ref-1", acad, now), lines=[], idempotency_key="ref:1"
    )

    upd = await repo.apply_invoice_refund(invoice_id="inv-ref-1", amount_cents=2_000)
    assert upd.refunded_cents == 2_000
    upd2 = await repo.apply_invoice_refund(invoice_id="inv-ref-1", amount_cents=1_500)
    assert upd2.refunded_cents == 3_500

    raw = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-ref-1"})
    assert raw is not None
    assert raw["refunded_cents"] == 3_500
    reloaded = await repo.get_invoice("inv-ref-1")
    assert reloaded is not None
    assert reloaded.refunded_cents == 3_500


@pytest.mark.asyncio
async def test_apply_invoice_refund_rejects_over_refund(db, acad) -> None:
    """Defense-in-depth: cumulative refund can never exceed the invoice total, so a
    concurrent/buggy caller cannot push refunded_cents past what was ever collected."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-ceil-1", acad, now), lines=[], idempotency_key="ceil:1"
    )
    await repo.apply_invoice_refund(invoice_id="inv-ceil-1", amount_cents=7_000)
    # invoice total is 10_000; a further 4_000 would exceed it.
    with pytest.raises(ValueError, match="would exceed invoice total"):
        await repo.apply_invoice_refund(invoice_id="inv-ceil-1", amount_cents=4_000)
    reloaded = await repo.get_invoice("inv-ceil-1")
    assert reloaded is not None
    assert reloaded.refunded_cents == 7_000  # rejected write left state untouched


@pytest.mark.asyncio
async def test_reverse_invoice_refund_releases_claim(db, acad) -> None:
    """A claimed refund that fails downstream (e.g. Stripe raised) is released so the invoice
    projection does not show a refund that never happened."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-rev-1", acad, now), lines=[], idempotency_key="rev:1"
    )
    await repo.apply_invoice_refund(invoice_id="inv-rev-1", amount_cents=2_000)
    await repo.reverse_invoice_refund(invoice_id="inv-rev-1", amount_cents=2_000)
    reloaded = await repo.get_invoice("inv-rev-1")
    assert reloaded is not None
    assert reloaded.refunded_cents == 0


@pytest.mark.asyncio
async def test_sum_overpayment_credits_for_invoice(db, acad) -> None:
    """P0-3: the admin view's overpayment_credit_cents must be derivable from the credit
    ledger (no longer hardcoded 0)."""
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        _make_invoice("inv-oc-1", acad, now), lines=[], idempotency_key="oc:1"
    )
    from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
        RecordManualPayment,
        RecordManualPaymentCommand,
    )

    await RecordManualPayment(ledger=repo).execute(
        RecordManualPaymentCommand(
            invoice_id="inv-oc-1", amount_cents=12_500, payment_method="cash"
        )
    )
    assert await repo.sum_overpayment_credits_for_invoice("inv-oc-1") == 2_500
