"""A monthly invoice's tuition discount comes off exactly once, whatever touches it.

The generator writes a discounted month as a GROSS tuition line, a negative
``tuition_discount`` line, AND the same amount mirrored in the header's
``discount_cents``. ``recompute_totals`` used to sum the lines (already net of
the discount line) and then subtract ``discount_cents`` again, so every path
that recomputes the header — a late fee, an admin-added line, the create
back-fill — under-charged the family by the discount a second time.

These run the real use cases against the real Mongo ledger repository, seeded
with the exact shape ``MongoMonthlyBilling._dual_write_ledger_invoice`` writes.
The ACH autopay trigger lives in ``tests/unit/test_charge_autopay_use_case.py``
beside the Stripe fakes it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.apply_late_fees import ApplyLateFees
from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellation,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)

NOW = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
GROSS = 10_000
DISCOUNT = 2_000
NET = GROSS - DISCOUNT
INVOICE_ID = "ledger-monthly-enr-1-2026-08"
IDEMPOTENCY_KEY = "monthly-ledger-enr-1-2026-08"


def _generator_invoice(academy_id: str, *, due_date: date) -> LedgerInvoice:
    """The header ``_dual_write_ledger_invoice`` writes for a discounted month."""
    return LedgerInvoice(
        invoice_id=INVOICE_ID,
        academy_id=academy_id,
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enr-1",
        period="2026-08",
        status="open",
        subtotal_cents=GROSS,
        discount_cents=DISCOUNT,
        total_cents=NET,
        balance_due_cents=NET,
        currency="usd",
        due_date=due_date,
        created_at=NOW,
        updated_at=NOW,
    )


def _generator_lines(academy_id: str) -> list[InvoiceLine]:
    return [
        InvoiceLine(
            line_id="ledger-monthly-line-enr-1-2026-08",
            academy_id=academy_id,
            invoice_id=INVOICE_ID,
            line_type="tuition",
            description="Monthly tuition 2026-08",
            quantity=1,
            unit_amount_cents=GROSS,
            amount_cents=GROSS,
            source_type="payment",
            source_id="pay-legacy-1",
            created_at=NOW,
        ),
        InvoiceLine(
            line_id="ledger-monthly-line-enr-1-2026-08-discount",
            academy_id=academy_id,
            invoice_id=INVOICE_ID,
            line_type="discount",
            description="Sibling discount",
            quantity=1,
            unit_amount_cents=-DISCOUNT,
            amount_cents=-DISCOUNT,
            source_type="tuition_discount",
            source_id="disc-1",
            gross_cents=GROSS,
            net_cents=NET,
            created_at=NOW,
        ),
    ]


async def _seed(
    db, academy_id: str, *, due_date: date = date(2026, 8, 20)
) -> MongoBillingLedgerRepository:
    repo = MongoBillingLedgerRepository(db)
    await repo.create_invoice(
        _generator_invoice(academy_id, due_date=due_date),
        lines=_generator_lines(academy_id),
        idempotency_key=IDEMPOTENCY_KEY,
    )
    return repo


@pytest.mark.asyncio
async def test_admin_added_line_adds_only_its_own_amount(db, acad) -> None:
    repo = await _seed(db, acad)

    result = await AddInvoiceLine(ledger=repo, clock=lambda: NOW).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Racket",
            line_type="equipment",
            unit_amount_cents=3_000,
        )
    )

    stored = await repo.get_invoice(INVOICE_ID)
    assert stored is not None
    # $80 net tuition + $30 racket. The double count billed $90.
    assert result.invoice.total_cents == NET + 3_000
    assert stored.total_cents == NET + 3_000
    assert stored.balance_due_cents == NET + 3_000
    # The generator's header shape survives: subtotal gross, discount mirrored.
    assert stored.subtotal_cents == GROSS + 3_000
    assert stored.discount_cents == DISCOUNT


@dataclass(frozen=True)
class _Fees:
    late_fee_cents: int | None
    grace_days: int | None


class _FeesReader:
    def __init__(self, fees: _Fees) -> None:
        self._fees = fees

    async def execute(self, academy_id: str) -> _Fees:
        return self._fees


@pytest.mark.asyncio
async def test_late_fee_adds_only_the_fee(db, acad) -> None:
    repo = await _seed(db, acad, due_date=NOW.date() - timedelta(days=10))
    use_case = ApplyLateFees(
        ledger=repo,
        add_line=AddInvoiceLine(ledger=repo, clock=lambda: NOW),
        fees=_FeesReader(_Fees(late_fee_cents=1_500, grace_days=5)),
        clock=lambda: NOW,
    )

    result = await use_case.execute(academy_id=acad)

    assert result.applied == 1
    stored = await repo.get_invoice(INVOICE_ID)
    assert stored is not None
    # $80 net tuition + $15 fee. The double count billed $75: the fee cost
    # the family $5 LESS than paying on time.
    assert stored.total_cents == NET + 1_500
    assert stored.balance_due_cents == NET + 1_500


@pytest.mark.asyncio
async def test_create_invoice_backfilling_a_missing_line_keeps_the_net_total(db, acad) -> None:
    """A run that crashed after the header but before the discount line.

    The rerun's ``create_invoice`` back-fills the line and recomputes the
    header from the stored lines.
    """
    repo = MongoBillingLedgerRepository(db)
    tuition_line, _discount_line = _generator_lines(acad)
    await repo.create_invoice(
        _generator_invoice(acad, due_date=date(2026, 8, 20)),
        lines=[tuition_line],
        idempotency_key=IDEMPOTENCY_KEY,
    )

    repaired = await repo.create_invoice(
        _generator_invoice(acad, due_date=date(2026, 8, 20)),
        lines=_generator_lines(acad),
        idempotency_key=IDEMPOTENCY_KEY,
    )

    assert repaired.total_cents == NET
    assert repaired.balance_due_cents == NET
    stored = await repo.get_invoice(INVOICE_ID)
    assert stored is not None
    assert stored.total_cents == NET


@pytest.mark.asyncio
async def test_payment_then_line_keeps_the_payment_and_the_net_total(db, acad) -> None:
    """Allocations are preserved and the balance is net tuition + line - paid."""
    repo = await _seed(db, acad)
    now = NOW
    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-cash-1",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=5_000,
            unapplied_amount_cents=5_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="cash-1",
    )
    await repo.allocate_payment(
        payment_id="pay-cash-1",
        invoice_id=INVOICE_ID,
        amount_cents=5_000,
        idempotency_key="alloc-cash-1",
    )

    await AddInvoiceLine(ledger=repo, clock=lambda: NOW).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Shuttles",
            line_type="equipment",
            unit_amount_cents=1_000,
        )
    )

    stored = await repo.get_invoice(INVOICE_ID)
    assert stored is not None
    assert stored.total_cents == NET + 1_000
    assert stored.balance_due_cents == NET + 1_000 - 5_000
    assert stored.status == "partially_paid"


class _NoCredits:
    async def find_by_source(self, **_kwargs):  # pragma: no cover - not reached
        return None


@pytest.mark.asyncio
async def test_occurrence_cancellation_reads_net_tuition_after_a_line_is_added(db, acad) -> None:
    """Occurrence cancellation never recomputes the header: it prices the credit
    from the tuition and discount LINES, so it was already immune (#671). Pinned
    here so a later "simplify to subtotal - discount" cannot reintroduce it."""
    repo = await _seed(db, acad)
    await AddInvoiceLine(ledger=repo, clock=lambda: NOW).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Racket",
            line_type="equipment",
            unit_amount_cents=3_000,
        )
    )
    invoice = await repo.get_invoice(INVOICE_ID)
    assert invoice is not None
    use_case = ApplyOccurrenceCancellation(
        reader=None,  # type: ignore[arg-type]
        overrides=None,  # type: ignore[arg-type]
        invoices=repo,
        credits=_NoCredits(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    assert await use_case._tuition_cents(invoice) == NET
