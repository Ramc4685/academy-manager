"""Account credit applied by the monthly generator survives every header recompute.

The generator spends available account credit on the month's charge and writes
``total_cents = net - applied_credit``. The credit used to live ONLY in that
header total: it was on no invoice line and no payment allocation. Every path
that recomputes the header from the lines — an admin-added line, the hourly
late-fee pass, the ACH autopay discount line, the ``create_invoice`` back-fill —
raised the total back to net, so the family was billed the credit amount again
while the credit itself stayed consumed.

The credit is now an ``account_credit`` line, which ``recompute_totals`` takes
below the subtotal. These drive the REAL generator against the real Mongo
ledger and credit repositories, then touch the invoice the way production does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from backend.scripts.ledger_credit_line_audit import audit
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.apply_late_fees import ApplyLateFees
from backend.v2.contexts.billing.domain.ledger import ACCOUNT_CREDIT_SOURCE_TYPE
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository

GENERATED_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
GROSS = 10_000
CREDIT = 3_750
OWED = GROSS - CREDIT
INVOICE_ID = "inv-monthly-enroll-1-2026-06"
TUITION_LINE_ID = "line-monthly-enroll-1-2026-06"


async def _generate_credited_invoice(db, acad: str) -> MongoBillingLedgerRepository:
    """Run the real monthly generator for a family holding $37.50 of credit."""
    credits = MongoCreditLedgerRepository(db)
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: GENERATED_AT,
        credit_ledger=credits,
        ledger_repo=ledger_repo,
    )
    created = datetime(2026, 5, 20, tzinfo=UTC)
    await credits.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enroll-1",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=CREDIT,
            remaining_amount_cents=CREDIT,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-credit",
            created_at=created,
            updated_at=created,
        )
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-credit",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "days_of_week": ["Mon", "Wed"],
            "start_time": "18:00",
            "end_time": "19:00",
            "monthly_price_cents": GROSS,
            "capacity": 8,
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "student-1",
            "parent_id": "parent-1",
            "full_name": "A Student",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-1",
            "session_id": "sess-credit",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2026, 5, 1, tzinfo=UTC),
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    assert await credits.balance_for_parent("parent-1") == 0
    invoice = await ledger_repo.get_invoice(INVOICE_ID)
    assert invoice is not None
    assert invoice.subtotal_cents == GROSS
    assert invoice.total_cents == OWED
    assert invoice.balance_due_cents == OWED
    return ledger_repo


@pytest.mark.asyncio
async def test_generator_records_the_applied_credit_as_a_line(db, acad) -> None:
    ledger_repo = await _generate_credited_invoice(db, acad)

    lines = await ledger_repo.get_lines_for_invoice(INVOICE_ID)
    credit_lines = [line for line in lines if line.source_type == ACCOUNT_CREDIT_SOURCE_TYPE]
    assert len(credit_lines) == 1
    assert credit_lines[0].amount_cents == -CREDIT
    # Keyed by the payment id the credit application is recorded under, so the
    # line joins back to ``account_credit_ledger.applications``.
    tuition = next(line for line in lines if line.line_id == TUITION_LINE_ID)
    assert credit_lines[0].source_id == tuition.source_id


@pytest.mark.asyncio
async def test_admin_added_line_does_not_bill_the_credit_again(db, acad) -> None:
    ledger_repo = await _generate_credited_invoice(db, acad)

    await AddInvoiceLine(ledger=ledger_repo, clock=lambda: GENERATED_AT).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Racket",
            line_type="equipment",
            unit_amount_cents=3_000,
        )
    )

    stored = await ledger_repo.get_invoice(INVOICE_ID)
    assert stored is not None
    # $62.50 owed + $30 racket. The header-only credit billed $130.
    assert stored.total_cents == OWED + 3_000
    assert stored.balance_due_cents == OWED + 3_000
    # The subtotal stays the gross charges; the credit sits below it.
    assert stored.subtotal_cents == GROSS + 3_000


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
async def test_late_fee_does_not_bill_the_credit_again(db, acad) -> None:
    ledger_repo = await _generate_credited_invoice(db, acad)
    invoice = await ledger_repo.get_invoice(INVOICE_ID)
    assert invoice is not None
    later = datetime.combine(invoice.due_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=10)
    use_case = ApplyLateFees(
        ledger=ledger_repo,
        add_line=AddInvoiceLine(ledger=ledger_repo, clock=lambda: later),
        fees=_FeesReader(_Fees(late_fee_cents=1_500, grace_days=5)),
        clock=lambda: later,
    )

    result = await use_case.execute(academy_id=acad)

    assert result.applied == 1
    stored = await ledger_repo.get_invoice(INVOICE_ID)
    assert stored is not None
    # $62.50 owed + $15 fee. The header-only credit billed $115.
    assert stored.total_cents == OWED + 1_500
    assert stored.balance_due_cents == OWED + 1_500


@pytest.mark.asyncio
async def test_create_invoice_backfill_keeps_the_credit(db, acad) -> None:
    """A rerun whose ``create_invoice`` back-fills a line recomputes the header."""
    ledger_repo = await _generate_credited_invoice(db, acad)
    invoice = await ledger_repo.get_invoice(INVOICE_ID)
    assert invoice is not None
    lines = await ledger_repo.get_lines_for_invoice(INVOICE_ID)
    tuition = next(line for line in lines if line.line_id == TUITION_LINE_ID)
    await db["invoice_lines"].delete_one({"academy_id": acad, "line_id": TUITION_LINE_ID})

    repaired = await ledger_repo.create_invoice(
        invoice,
        lines=[tuition],
        idempotency_key="monthly-ledger-enroll-1-2026-06",
    )

    assert repaired.total_cents == OWED
    assert repaired.balance_due_cents == OWED


async def _strip_credit_line(db, acad: str) -> None:
    """Rewind a generated invoice to the pre-fix, header-only credit shape."""
    await db["invoice_lines"].delete_many(
        {"academy_id": acad, "invoice_id": INVOICE_ID, "source_type": ACCOUNT_CREDIT_SOURCE_TYPE}
    )


@pytest.mark.asyncio
async def test_audit_backfills_the_line_on_a_legacy_invoice_still_net_of_credit(db, acad) -> None:
    ledger_repo = await _generate_credited_invoice(db, acad)
    await _strip_credit_line(db, acad)

    report = await audit(db)

    assert report["at_risk_count"] == 1
    assert report["overcharged_count"] == 0
    assert report["credit_lines_inserted"] == 0
    assert (
        await db["invoice_lines"].count_documents(
            {"invoice_id": INVOICE_ID, "source_type": ACCOUNT_CREDIT_SOURCE_TYPE}
        )
        == 0
    )

    applied = await audit(db, apply=True)
    assert applied["credit_lines_inserted"] == 1
    # Idempotent: the line is now there, so the invoice is no longer at risk.
    rerun = await audit(db, apply=True)
    assert rerun["at_risk_count"] == 0
    assert rerun["invoices_with_credit_line"] == 1

    # And the back-filled line protects the next recompute.
    await AddInvoiceLine(ledger=ledger_repo, clock=lambda: GENERATED_AT).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Racket",
            line_type="equipment",
            unit_amount_cents=3_000,
        )
    )
    stored = await ledger_repo.get_invoice(INVOICE_ID)
    assert stored is not None
    assert stored.total_cents == OWED + 3_000


@pytest.mark.asyncio
async def test_audit_reports_but_never_rewrites_an_already_overcharged_invoice(db, acad) -> None:
    ledger_repo = await _generate_credited_invoice(db, acad)
    await _strip_credit_line(db, acad)
    # The pre-fix recompute: the racket raised the total back to gross + racket.
    await AddInvoiceLine(ledger=ledger_repo, clock=lambda: GENERATED_AT).execute(
        AddInvoiceLineCommand(
            invoice_id=INVOICE_ID,
            description="Racket",
            line_type="equipment",
            unit_amount_cents=3_000,
        )
    )
    before = await ledger_repo.get_invoice(INVOICE_ID)
    assert before is not None
    assert before.total_cents == GROSS + 3_000

    report = await audit(db, apply=True)

    assert report["overcharged_count"] == 1
    assert report["overcharged_cents"] == CREDIT
    assert report["collected_excess_cents"] == 0
    row = report["overcharged"][0]
    assert row["expected_total_cents"] == OWED + 3_000
    assert report["credit_lines_inserted"] == 0
    after = await ledger_repo.get_invoice(INVOICE_ID)
    assert after is not None
    assert after.total_cents == before.total_cents
