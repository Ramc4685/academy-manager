"""``ApplyOccurrenceCancellation`` — the money side of issue #671.

The credit ledger fake mirrors migration 0168's unique
``(academy_id, source_type, source_id)`` index: ``create_if_absent`` refuses a
second write for the same source. A permissive fake here would hide exactly
the double-credit this feature must never produce (PR #664 postmortem).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellation,
    ApplyOccurrenceCancellationCommand,
    BillableEnrollment,
    PeriodChargeBasis,
    SessionPricing,
)
from backend.v2.contexts.billing.domain.credits import (
    CLASS_CANCELLATION_SOURCE_TYPE,
    class_cancellation_credit_cents,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.domain.proration import ClassOccurrence

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
TZ = "America/Chicago"
# Four Thursdays in September 2026, 18:00 local = 23:00 UTC.
DATES = [datetime(2026, 9, day, 23, 0, tzinfo=UTC) for day in (3, 10, 17, 24)]


def _occurrence(index: int, *, status: str = "scheduled", billable: bool = True) -> ClassOccurrence:
    start = DATES[index]
    return ClassOccurrence(
        occurrence_id=f"sess-1:{start.date().isoformat()}:18:00",
        session_id="sess-1",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        is_billable=billable,
        timezone=TZ,
    )


@dataclass
class FakeReader:
    pricing: SessionPricing | None = field(
        default_factory=lambda: SessionPricing(
            session_id="sess-1", timezone=TZ, monthly_price_cents=12000
        )
    )
    occurrences: list[ClassOccurrence] = field(
        default_factory=lambda: [_occurrence(i) for i in range(4)]
    )
    enrollments: list[BillableEnrollment] = field(default_factory=list)
    #: enrollment_id (or "student:session") -> what was priced for the period.
    bases: dict[str, PeriodChargeBasis] = field(default_factory=dict)

    async def session_pricing(self, session_id: str) -> SessionPricing | None:
        return self.pricing

    async def occurrences_for_period(
        self, *, session_id: str, period: str
    ) -> list[ClassOccurrence]:
        return list(self.occurrences)

    async def period_charge_basis(
        self, *, enrollment_id: str, student_id: str, session_id: str, period: str
    ) -> PeriodChargeBasis | None:
        return self.bases.get(enrollment_id) or self.bases.get(f"{student_id}:{session_id}")

    async def enrollments_for_session(self, session_id: str) -> list[BillableEnrollment]:
        return list(self.enrollments)


@dataclass
class FakeOverrides:
    written: list[dict[str, Any]] = field(default_factory=list)

    async def mark_cancelled(self, **kwargs: Any) -> None:
        self.written.append(kwargs)


@dataclass
class FakeInvoices:
    rows: dict[str, LedgerInvoice] = field(default_factory=dict)
    #: invoice_id -> its lines, mirroring ``get_lines_for_invoice``.
    lines: dict[str, list[InvoiceLine]] = field(default_factory=dict)

    async def get_invoice_for_enrollment_period(
        self, enrollment_id: str, period: str, *, statuses: set[str] | None = None
    ) -> LedgerInvoice | None:
        return self.rows.get(enrollment_id)

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return list(self.lines.get(invoice_id, []))


@dataclass
class FakeCredits:
    """Mirrors the real store: the unique source index rejects a duplicate."""

    rows: list[CreditLedgerEntry] = field(default_factory=list)

    async def create_if_absent(self, entry: CreditLedgerEntry) -> bool:
        if entry.source_type and entry.source_id:
            existing = await self.find_by_source(
                source_type=entry.source_type, source_id=entry.source_id
            )
            if existing is not None:
                return False
        self.rows.append(entry)
        return True

    async def find_by_source(self, *, source_type: str, source_id: str) -> CreditLedgerEntry | None:
        for row in self.rows:
            if row.source_type == source_type and row.source_id == source_id:
                return row
        return None


def _invoice(enrollment_id: str, *, subtotal: int, discount: int = 0, status: str = "open"):
    return LedgerInvoice(
        invoice_id=f"inv-{enrollment_id}",
        academy_id="acad",
        parent_id="par-1",
        enrollment_id=enrollment_id,
        period="2026-09",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=subtotal,
        discount_cents=discount,
        total_cents=max(subtotal - discount, 0),
        balance_due_cents=max(subtotal - discount, 0),
        due_date=NOW.date(),
        invoice_number="BLNO-202609-001",
        created_at=NOW,
        updated_at=NOW,
    )


def _enrollment(enrollment_id: str, **overrides: Any) -> BillableEnrollment:
    base: dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "parent_id": f"par-{enrollment_id}",
        "student_id": f"st-{enrollment_id}",
        "status": "active",
        "billing_start_at": None,
    }
    base.update(overrides)
    return BillableEnrollment(**base)


def _cmd(**overrides: Any) -> ApplyOccurrenceCancellationCommand:
    base: dict[str, Any] = {
        "occurrence_id": "occ-1",
        "session_id": "sess-1",
        "start_at": DATES[1],
        "reason": "gym flooded",
        "actor_id": "u-1",
    }
    base.update(overrides)
    return ApplyOccurrenceCancellationCommand(**base)


def _build(
    reader: FakeReader, invoices: FakeInvoices, credits: FakeCredits, overrides: FakeOverrides
):
    return ApplyOccurrenceCancellation(
        reader=reader,  # type: ignore[arg-type]
        overrides=overrides,  # type: ignore[arg-type]
        invoices=invoices,  # type: ignore[arg-type]
        credits=credits,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


def test_credit_is_one_class_share_rounded_half_up() -> None:
    # 12000 over 4 classes is exact; 10000 over 3 is 3333.33 -> 3333.
    assert class_cancellation_credit_cents(period_charge_cents=12000, billable_classes=4) == 3000
    assert class_cancellation_credit_cents(period_charge_cents=10000, billable_classes=3) == 3333
    assert class_cancellation_credit_cents(period_charge_cents=10000, billable_classes=4) == 2500
    assert class_cancellation_credit_cents(period_charge_cents=0, billable_classes=4) == 0
    assert class_cancellation_credit_cents(period_charge_cents=12000, billable_classes=0) == 0


@pytest.mark.asyncio
async def test_override_written_and_invoiced_family_credited() -> None:
    reader = FakeReader(enrollments=[_enrollment("enr-1")])
    invoices = FakeInvoices({"enr-1": _invoice("enr-1", subtotal=12000)})
    credits, overrides = FakeCredits(), FakeOverrides()

    result = await _build(reader, invoices, credits, overrides).execute(_cmd())

    assert result.period == "2026-09"
    assert result.override_written is True
    assert overrides.written[0]["occurrence_id"] == "sess-1:2026-09-10:18:00"
    assert overrides.written[0]["source_occurrence_id"] == "occ-1"
    assert [row.amount_cents for row in credits.rows] == [3000]
    entry = credits.rows[0]
    assert entry.type == "CLASS_CANCELLATION_CREDIT"
    assert entry.status == "APPROVED"
    assert entry.remaining_amount_cents == 3000
    assert entry.source_type == CLASS_CANCELLATION_SOURCE_TYPE
    assert entry.source_id == "occ-1:enr-1"
    assert entry.parent_id == "par-enr-1"
    assert "2026-09-10" in entry.reason
    assert result.credits == {"enr-1": entry.credit_id}
    assert result.billing_result.startswith("credited=1")


@pytest.mark.asyncio
async def test_invoice_discount_lowers_the_credit() -> None:
    reader = FakeReader(enrollments=[_enrollment("enr-1")])
    invoices = FakeInvoices({"enr-1": _invoice("enr-1", subtotal=12000, discount=4000)})
    credits = FakeCredits()

    await _build(reader, invoices, credits, FakeOverrides()).execute(_cmd())

    assert credits.rows[0].amount_cents == 2000  # (12000 - 4000) / 4


@pytest.mark.asyncio
async def test_second_run_credits_nobody_twice() -> None:
    reader = FakeReader(enrollments=[_enrollment("enr-1")])
    invoices = FakeInvoices({"enr-1": _invoice("enr-1", subtotal=12000)})
    credits, overrides = FakeCredits(), FakeOverrides()
    use_case = _build(reader, invoices, credits, overrides)

    first = await use_case.execute(_cmd())
    second = await use_case.execute(_cmd())

    assert len(credits.rows) == 1
    assert second.credits == first.credits
    assert "credited=0" in second.billing_result
    assert "existing=1" in second.billing_result


@pytest.mark.asyncio
async def test_void_invoice_is_skipped() -> None:
    reader = FakeReader(enrollments=[_enrollment("enr-1")])
    invoices = FakeInvoices({"enr-1": _invoice("enr-1", subtotal=12000, status="void")})
    credits = FakeCredits()

    result = await _build(reader, invoices, credits, FakeOverrides()).execute(_cmd())

    assert credits.rows == []
    assert result.decisions[0].outcome == "skipped:invoice_void"


@pytest.mark.asyncio
async def test_paused_family_with_no_invoice_is_skipped() -> None:
    reader = FakeReader(enrollments=[_enrollment("enr-1", status="paused")])
    credits = FakeCredits()

    result = await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(_cmd())

    assert credits.rows == []
    assert result.decisions[0].outcome == "skipped:paused_not_invoiced"


@pytest.mark.asyncio
async def test_first_month_family_is_prorated_not_credited() -> None:
    # Rule 1 already excludes the date from their proration; crediting too
    # would pay the cancelled class back twice.
    reader = FakeReader(enrollments=[_enrollment("enr-1", billing_start_at=DATES[0])])
    credits = FakeCredits()

    result = await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(_cmd())

    assert credits.rows == []
    assert result.decisions[0].outcome == "skipped:first_month_proration_excludes_date"


@pytest.mark.asyncio
async def test_uninvoiced_ongoing_family_is_credited_from_the_monthly_price() -> None:
    reader = FakeReader(
        enrollments=[
            _enrollment("enr-1", billing_start_at=datetime(2026, 6, 1, tzinfo=UTC)),
        ]
    )
    credits = FakeCredits()

    await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(_cmd())

    assert credits.rows[0].amount_cents == 3000


@pytest.mark.asyncio
async def test_recurring_discount_lowers_the_uninvoiced_credit() -> None:
    reader = FakeReader(
        enrollments=[
            _enrollment(
                "enr-1",
                billing_start_at=datetime(2026, 6, 1, tzinfo=UTC),
                monthly_discount_cents=4000,
            )
        ]
    )
    credits = FakeCredits()

    await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(_cmd())

    assert credits.rows[0].amount_cents == 2000


@pytest.mark.asyncio
async def test_an_earlier_cancellation_does_not_shrink_the_divisor() -> None:
    # The month was priced with four classes in it. One is already cancelled;
    # crediting 1/3 of the month for the second would over-refund.
    reader = FakeReader(
        occurrences=[
            _occurrence(0, status="canceled", billable=False),
            _occurrence(1),
            _occurrence(2),
            _occurrence(3),
        ],
        enrollments=[_enrollment("enr-1")],
    )
    invoices = FakeInvoices({"enr-1": _invoice("enr-1", subtotal=12000)})
    credits = FakeCredits()

    await _build(reader, invoices, credits, FakeOverrides()).execute(_cmd())

    assert credits.rows[0].amount_cents == 3000  # 12000 / 4, not / 3


@pytest.mark.asyncio
async def test_date_the_generator_never_priced_writes_an_override_and_credits_nobody() -> None:
    reader = FakeReader(occurrences=[], enrollments=[_enrollment("enr-1")])
    credits, overrides = FakeCredits(), FakeOverrides()

    result = await _build(reader, FakeInvoices(), credits, overrides).execute(_cmd())

    assert credits.rows == []
    assert result.override_written is False
    assert overrides.written[0]["occurrence_id"] == "sess-1:2026-09-10:18:00"


@pytest.mark.asyncio
async def test_missing_session_is_reported_not_crashed() -> None:
    reader = FakeReader(pricing=None)
    overrides = FakeOverrides()

    result = await _build(reader, FakeInvoices(), FakeCredits(), overrides).execute(_cmd())

    assert result.billing_occurrence_id is None
    assert overrides.written == []


def _line(invoice_id: str, *, line_type: str, amount: int, line_id: str) -> InvoiceLine:
    return InvoiceLine(
        line_id=line_id,
        academy_id="acad",
        invoice_id=invoice_id,
        line_type=line_type,
        description=line_type,
        quantity=1,
        unit_amount_cents=amount,
        amount_cents=amount,
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_non_tuition_invoice_lines_do_not_inflate_the_credit() -> None:
    # A $120 racket billed on the same September invoice must not be divided
    # by the month's classes and handed back as a cancellation credit.
    invoice = _invoice("enr-1", subtotal=32000)
    invoices = FakeInvoices(
        rows={"enr-1": invoice},
        lines={
            "inv-enr-1": [
                _line("inv-enr-1", line_type="tuition", amount=20000, line_id="l-1"),
                _line("inv-enr-1", line_type="equipment", amount=12000, line_id="l-2"),
            ]
        },
    )
    credits = FakeCredits()

    await _build(
        FakeReader(enrollments=[_enrollment("enr-1")]), invoices, credits, FakeOverrides()
    ).execute(_cmd())

    assert credits.rows[0].amount_cents == 5000  # 20000 / 4, not 32000 / 4


@pytest.mark.asyncio
async def test_credit_divisor_is_the_classes_the_prorated_invoice_bought() -> None:
    # Late first-month generation: charge = base * 1/4, so the family paid for
    # exactly ONE class. Cancelling it credits the whole charge, not a quarter.
    reader = FakeReader(
        enrollments=[_enrollment("enr-1", billing_start_at=datetime(2026, 9, 1, tzinfo=UTC))],
        bases={
            "enr-1": PeriodChargeBasis(
                calculation_type="FIRST_MONTH_PRORATION",
                final_amount_cents=3000,
                total_eligible_classes=4,
                billable_remaining_classes=1,
                included_occurrence_ids=("sess-1:2026-09-24:18:00",),
            )
        },
    )
    invoices = FakeInvoices(
        rows={"enr-1": _invoice("enr-1", subtotal=3000)},
        lines={"inv-enr-1": [_line("inv-enr-1", line_type="tuition", amount=3000, line_id="l-1")]},
    )
    credits = FakeCredits()

    await _build(reader, invoices, credits, FakeOverrides()).execute(_cmd(start_at=DATES[3]))

    assert credits.rows[0].amount_cents == 3000  # 3000 / 1, not 3000 / 4


@pytest.mark.asyncio
async def test_a_date_the_prorated_charge_never_covered_is_not_credited() -> None:
    reader = FakeReader(
        enrollments=[_enrollment("enr-1", billing_start_at=datetime(2026, 9, 1, tzinfo=UTC))],
        bases={
            "enr-1": PeriodChargeBasis(
                calculation_type="FIRST_MONTH_PRORATION",
                final_amount_cents=3000,
                total_eligible_classes=4,
                billable_remaining_classes=1,
                included_occurrence_ids=("sess-1:2026-09-24:18:00",),
            )
        },
    )
    invoices = FakeInvoices(
        rows={"enr-1": _invoice("enr-1", subtotal=3000)},
        lines={"inv-enr-1": [_line("inv-enr-1", line_type="tuition", amount=3000, line_id="l-1")]},
    )
    credits = FakeCredits()

    result = await _build(reader, invoices, credits, FakeOverrides()).execute(_cmd())

    assert credits.rows == []
    assert result.decisions[0].outcome == "skipped:date_not_billed"


@pytest.mark.asyncio
async def test_mid_month_checkout_family_with_no_invoice_is_credited() -> None:
    # Registration checkout: the first month is PAID, the snapshot is CONSUMED
    # with no enrollment_id, and no ledger invoice is keyed to
    # (enrollment, period) — the generator will never re-price the month. The
    # family must still get the cancelled date back (#671).
    enrollment = _enrollment("enr-1", billing_start_at=DATES[0])
    reader = FakeReader(
        enrollments=[enrollment],
        bases={
            f"{enrollment.student_id}:sess-1": PeriodChargeBasis(
                calculation_type="FIRST_MONTH_PRORATION",
                final_amount_cents=9000,
                total_eligible_classes=4,
                billable_remaining_classes=3,
                included_occurrence_ids=(
                    "sess-1:2026-09-10:18:00",
                    "sess-1:2026-09-17:18:00",
                    "sess-1:2026-09-24:18:00",
                ),
            )
        },
    )
    credits = FakeCredits()

    result = await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(_cmd())

    assert credits.rows[0].amount_cents == 3000  # 9000 / 3
    assert result.decisions[0].outcome == "credited"


# ---------------------------------------------------------------------------
# The month's FREE extra classes (4 paid per weekly meeting).
# ---------------------------------------------------------------------------

#: Five Wednesdays in September 2026 — a month that lays out one more class
#: than the monthly tuition buys.
WEDNESDAYS = [datetime(2026, 9, day, 23, 0, tzinfo=UTC) for day in (2, 9, 16, 23, 30)]


def _wednesday(index: int, *, status: str = "scheduled") -> ClassOccurrence:
    start = WEDNESDAYS[index]
    return ClassOccurrence(
        occurrence_id=f"sess-1:{start.date().isoformat()}:18:00",
        session_id="sess-1",
        start_at=start,
        end_at=start + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        is_billable=status != "cancelled",
        timezone=TZ,
    )


def _five_class_basis() -> PeriodChargeBasis:
    """$70 paid for a 5-class first month: 4 classes charged, the 5th free."""
    return PeriodChargeBasis(
        calculation_type="FIRST_MONTH_PRORATION",
        final_amount_cents=7000,
        total_eligible_classes=5,
        billable_remaining_classes=5,
        billable_classes_denominator=4,
        included_occurrence_ids=tuple(_wednesday(i).occurrence_id for i in range(5)),
    )


@pytest.mark.asyncio
async def test_no_credit_while_the_free_extra_class_absorbs_the_cancellation() -> None:
    """The family paid for 4 classes and 4 still run, so they lost nothing.

    Dividing the $70 charge by the 5 scheduled dates would refund $14 — money
    the academy never took, at a rate that contradicts the $17.50/class the
    invoice line states.
    """
    enrollment = _enrollment("enr-1", billing_start_at=WEDNESDAYS[0])
    reader = FakeReader(
        occurrences=[_wednesday(i) for i in range(5)],
        enrollments=[enrollment],
        bases={f"{enrollment.student_id}:sess-1": _five_class_basis()},
    )
    credits = FakeCredits()

    result = await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(
        _cmd(start_at=WEDNESDAYS[2])
    )

    assert credits.rows == []
    assert result.decisions[0].outcome == "skipped:covered_by_free_classes"


@pytest.mark.asyncio
async def test_second_cancellation_credits_at_the_charged_per_class_rate() -> None:
    """Once the free 5th class is gone, each further cancellation costs a class.

    The rate is the one the family was charged at — $70 / 4 — not $70 / 5.
    """
    enrollment = _enrollment("enr-1", billing_start_at=WEDNESDAYS[0])
    occurrences = [_wednesday(i) for i in range(5)]
    occurrences[1] = _wednesday(1, status="cancelled")
    reader = FakeReader(
        occurrences=occurrences,
        enrollments=[enrollment],
        bases={f"{enrollment.student_id}:sess-1": _five_class_basis()},
    )
    credits = FakeCredits()

    result = await _build(reader, FakeInvoices(), credits, FakeOverrides()).execute(
        _cmd(start_at=WEDNESDAYS[2])
    )

    assert result.decisions[0].outcome == "credited"
    assert credits.rows[0].amount_cents == 1750
