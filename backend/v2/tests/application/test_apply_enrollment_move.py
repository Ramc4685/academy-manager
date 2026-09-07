"""Issue #669: ``ApplyEnrollmentMove`` re-prices the current period.

The fakes mirror the real stores: ``save_invoice`` enforces the version
token, ``save_line`` upserts by ``line_id``, ``create_invoice`` is idempotent
on its key with ``$setOnInsert`` lines, and the credit ledger rejects a
duplicate ``credit_id``. A permissive fake would hide exactly the double-apply
bugs this use case exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    MOVE_CREDIT_TYPE,
    MOVE_LINE_TYPE,
    MOVE_SOURCE_TYPE,
    ApplyEnrollmentMove,
    ApplyEnrollmentMoveCommand,
    MoveSessionSchedule,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.domain.proration import ClassOccurrence

TZ = "America/Chicago"
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
EFFECTIVE = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
ACADEMY = "acad-move"


@pytest.fixture(autouse=True)
def _tenant():
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(ACADEMY)
    try:
        yield
    finally:
        try:
            _tv.reset(token)
        except (ValueError, LookupError):
            pass


def _occ(session_id: str, day: int) -> ClassOccurrence:
    start = datetime(2026, 9, day, 18, 0, tzinfo=ZoneInfo(TZ))
    return ClassOccurrence(
        occurrence_id=f"{session_id}:2026-09-{day:02d}:18:00",
        session_id=session_id,
        start_at=start.astimezone(UTC),
        end_at=start.astimezone(UTC),
        status="scheduled",
        is_billable=True,
        timezone=TZ,
    )


def _schedule(session_id: str, price: int, days: tuple[int, ...]) -> MoveSessionSchedule:
    return MoveSessionSchedule(
        session_id=session_id,
        monthly_price_cents=price,
        timezone=TZ,
        occurrences=[_occ(session_id, d) for d in days],
    )


def _invoice(
    invoice_id: str = "inv-enr-1-2026-09",
    *,
    status: str = "open",
    total: int = 8000,
    period: str = "2026-09",
) -> LedgerInvoice:
    balance = 0 if status == "paid" else total
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=ACADEMY,
        parent_id="par-1",
        student_id="stu-1",
        enrollment_id="enr-1",
        period=period,
        status=status,  # type: ignore[arg-type]
        subtotal_cents=total,
        total_cents=total,
        balance_due_cents=balance,
        due_date=date(2026, 9, 8),
        created_at=NOW,
        updated_at=NOW,
    )


def _line(invoice: LedgerInvoice, amount: int) -> InvoiceLine:
    return InvoiceLine(
        line_id=f"line-tuition-{invoice.invoice_id}",
        academy_id=ACADEMY,
        invoice_id=invoice.invoice_id,
        line_type="tuition",
        description="September tuition",
        quantity=1,
        unit_amount_cents=amount,
        amount_cents=amount,
        created_at=NOW,
    )


@dataclass
class FakeLedger:
    invoices: dict[str, LedgerInvoice] = field(default_factory=dict)
    lines: dict[str, InvoiceLine] = field(default_factory=dict)
    allocations: dict[str, int] = field(default_factory=dict)
    idempotency: dict[str, str] = field(default_factory=dict)
    create_calls: int = 0

    def seed(self, invoice: LedgerInvoice, *lines: InvoiceLine) -> None:
        self.invoices[invoice.invoice_id] = invoice
        for line in lines:
            self.lines[line.line_id] = line
        if invoice.status == "paid":
            self.allocations[invoice.invoice_id] = invoice.total_cents

    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[LedgerInvoice]:
        rows = [i for i in self.invoices.values() if i.enrollment_id == enrollment_id]
        return sorted(rows, key=lambda i: (i.period, i.invoice_id))

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [line for line in self.lines.values() if line.invoice_id == invoice_id]

    async def sum_allocations_for_invoice(self, invoice_id: str) -> int:
        return self.allocations.get(invoice_id, 0)

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        existing = self.invoices.get(invoice.invoice_id)
        if existing is not None and existing.version != invoice.version:
            raise ValueError("invoice changed during save; retry")
        stored = invoice.model_copy(update={"version": invoice.version + (1 if existing else 0)})
        self.invoices[invoice.invoice_id] = stored
        return stored

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        self.lines[line.line_id] = line
        return line

    async def create_invoice(
        self, invoice: LedgerInvoice, *, lines: list[InvoiceLine], idempotency_key: str
    ) -> LedgerInvoice:
        self.create_calls += 1
        existing_id = self.idempotency.get(idempotency_key)
        if existing_id is not None:
            return self.invoices[existing_id]
        self.idempotency[idempotency_key] = invoice.invoice_id
        self.invoices[invoice.invoice_id] = invoice
        for line in lines:
            self.lines.setdefault(line.line_id, line)
        return invoice


@dataclass
class FakeCredits:
    rows: dict[str, CreditLedgerEntry] = field(default_factory=dict)

    async def create(self, entry: CreditLedgerEntry) -> None:
        if entry.credit_id in self.rows:
            raise ValueError("duplicate credit_id")
        self.rows[entry.credit_id] = entry

    async def find_active_for_enrollment(self, *, enrollment_id: str, type: str):
        rows = [
            c
            for c in self.rows.values()
            if c.enrollment_id == enrollment_id and c.type == type and c.status == "APPROVED"
        ]
        rows.sort(key=lambda c: (c.created_at, c.credit_id), reverse=True)
        return rows[0] if rows else None

    async def list_for_parent(self, parent_id: str):  # pragma: no cover - protocol filler
        return list(self.rows.values())

    async def balance_for_parent(self, parent_id: str) -> int:
        return sum(c.remaining_amount_cents for c in self.rows.values())

    async def apply_available_credits(self, **_: Any) -> int:  # pragma: no cover
        return 0

    async def applied_credit_state(self, invoice_id: str):  # pragma: no cover
        raise NotImplementedError

    async def repair_credit_projections(self, invoice_id: str) -> int:  # pragma: no cover
        return 0


@dataclass
class FakeSchedules:
    rows: dict[str, MoveSessionSchedule] = field(default_factory=dict)

    async def load(self, *, session_id: str, period: str) -> MoveSessionSchedule | None:
        return self.rows.get(session_id)


class InMemoryIdempotency:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.rows.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.rows[key] = value


def _build(ledger: FakeLedger, credits: FakeCredits, schedules: FakeSchedules):
    return ApplyEnrollmentMove(
        ledger=ledger,
        credits=credits,
        schedules=schedules,
        idempotency_store=InMemoryIdempotency(),
        academy_timezone=_tz,
        clock=lambda: NOW,
    )


async def _tz() -> str | None:
    return TZ


def _cmd(**overrides: Any) -> ApplyEnrollmentMoveCommand:
    base: dict[str, Any] = {
        "enrollment_id": "enr-1",
        "from_session_id": "sess-a",
        "to_session_id": "sess-b",
        "effective_at": EFFECTIVE,
        "reason": "schedule change",
        "actor_id": "admin-1",
    }
    base.update(overrides)
    return ApplyEnrollmentMoveCommand(**base)


def _schedules(from_price: int = 8000, to_price: int = 12000) -> FakeSchedules:
    return FakeSchedules(
        rows={
            "sess-a": _schedule("sess-a", from_price, (5, 12, 19, 26)),
            "sess-b": _schedule("sess-b", to_price, (6, 13, 20, 27)),
        }
    )


@pytest.mark.asyncio
async def test_debit_adds_move_line_to_open_invoice() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))

    result = await _build(ledger, credits, _schedules()).execute(_cmd())

    assert result.outcome == "debited"
    assert result.delta_cents == 3000
    assert result.billing_result == "debit:3000"
    updated = ledger.invoices[invoice.invoice_id]
    assert updated.total_cents == 11000
    assert updated.balance_due_cents == 11000
    assert updated.status == "open"
    lines = await ledger.get_lines_for_invoice(invoice.invoice_id)
    move_lines = [line for line in lines if line.line_type == MOVE_LINE_TYPE]
    assert len(move_lines) == 1
    assert move_lines[0].amount_cents == 3000
    assert move_lines[0].source_type == MOVE_SOURCE_TYPE
    assert move_lines[0].source_id == result.idempotency_key
    assert result.metadata["line_id"] == move_lines[0].line_id
    assert credits.rows == {}


@pytest.mark.asyncio
async def test_debit_on_partially_paid_invoice_keeps_recorded_money() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice(status="partially_paid").model_copy(update={"balance_due_cents": 3000})
    ledger.seed(invoice, _line(invoice, 8000))
    ledger.allocations[invoice.invoice_id] = 5000

    result = await _build(ledger, credits, _schedules()).execute(_cmd())

    assert result.outcome == "debited"
    updated = ledger.invoices[invoice.invoice_id]
    assert updated.total_cents == 11000
    assert updated.balance_due_cents == 6000
    assert updated.status == "partially_paid"


@pytest.mark.asyncio
async def test_credit_creates_move_proration_credit() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))

    result = await _build(ledger, credits, _schedules(12000, 8000)).execute(_cmd())

    assert result.outcome == "credited"
    assert result.delta_cents == -3000
    assert result.billing_result == "credit:3000"
    assert ledger.invoices[invoice.invoice_id].total_cents == 8000  # invoice untouched
    assert len(credits.rows) == 1
    credit = next(iter(credits.rows.values()))
    assert credit.type == MOVE_CREDIT_TYPE
    assert credit.status == "APPROVED"
    assert credit.amount_cents == credit.remaining_amount_cents == 3000
    assert credit.parent_id == "par-1"
    assert credit.enrollment_id == "enr-1"
    assert credit.source_id == result.idempotency_key
    assert credit.approved_by == "admin-1"
    assert result.metadata["credit_id"] == credit.credit_id


@pytest.mark.asyncio
async def test_zero_delta_records_only() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))

    result = await _build(ledger, credits, _schedules(8000, 8000)).execute(_cmd())

    assert result.outcome == "no_change"
    assert result.billing_result == "no_change"
    assert ledger.invoices[invoice.invoice_id].total_cents == 8000
    assert len(await ledger.get_lines_for_invoice(invoice.invoice_id)) == 1
    assert credits.rows == {}


@pytest.mark.asyncio
async def test_no_invoice_for_period_does_nothing() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    august = _invoice("inv-enr-1-2026-08", status="paid", period="2026-08")
    ledger.seed(august, _line(august, 8000))

    result = await _build(ledger, credits, _schedules()).execute(_cmd())

    assert result.outcome == "no_invoice"
    assert result.billing_result == "no_invoice"
    assert ledger.invoices[august.invoice_id].total_cents == 8000
    assert credits.rows == {}
    assert ledger.create_calls == 0


@pytest.mark.asyncio
async def test_paid_invoice_mints_separate_adjustment_invoice() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice(status="paid")
    ledger.seed(invoice, _line(invoice, 8000))

    result = await _build(ledger, credits, _schedules()).execute(_cmd())

    assert result.outcome == "adjustment_invoiced"
    assert result.billing_result == "debit:3000"
    # The paid invoice is never re-opened or re-priced.
    paid = ledger.invoices[invoice.invoice_id]
    assert paid.status == "paid" and paid.total_cents == 8000
    assert len(await ledger.get_lines_for_invoice(invoice.invoice_id)) == 1
    adjustment = ledger.invoices[result.invoice_id]
    assert adjustment.invoice_id != invoice.invoice_id
    assert adjustment.status == "open"
    assert adjustment.total_cents == adjustment.balance_due_cents == 3000
    assert adjustment.period == "2026-09"
    assert adjustment.parent_id == "par-1"
    assert adjustment.enrollment_id == "enr-1"  # what the autopay worker keys on
    assert adjustment.source_type == MOVE_SOURCE_TYPE
    assert adjustment.due_date == date(2026, 9, 16)
    lines = await ledger.get_lines_for_invoice(adjustment.invoice_id)
    assert [line.amount_cents for line in lines] == [3000]
    assert ledger.idempotency[result.idempotency_key] == adjustment.invoice_id


@pytest.mark.asyncio
async def test_repeat_move_is_idempotent_for_debit_credit_and_adjustment() -> None:
    # debit
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))
    use_case = _build(ledger, credits, _schedules())
    first = await use_case.execute(_cmd())
    second = await use_case.execute(_cmd())
    assert second == first
    assert ledger.invoices[invoice.invoice_id].total_cents == 11000
    assert len(await ledger.get_lines_for_invoice(invoice.invoice_id)) == 2

    # credit
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))
    use_case = _build(ledger, credits, _schedules(12000, 8000))
    first = await use_case.execute(_cmd())
    second = await use_case.execute(_cmd())
    assert second.credit_id == first.credit_id
    assert len(credits.rows) == 1

    # paid → adjustment invoice
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice(status="paid")
    ledger.seed(invoice, _line(invoice, 8000))
    use_case = _build(ledger, credits, _schedules())
    first = await use_case.execute(_cmd())
    second = await use_case.execute(_cmd())
    assert second.invoice_id == first.invoice_id
    assert len([i for i in ledger.invoices.values() if i.source_type == MOVE_SOURCE_TYPE]) == 1


@pytest.mark.asyncio
async def test_repeat_without_cached_result_still_does_not_double_apply() -> None:
    """A crash between the ledger write and the idempotency put must not
    double-apply on retry: the line, credit and invoice are each keyed."""
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))
    schedules = _schedules()
    first_uc = _build(ledger, credits, schedules)
    first = await first_uc.execute(_cmd())
    # fresh idempotency store, same ledger → retry path
    retry_uc = _build(ledger, credits, schedules)
    second = await retry_uc.execute(_cmd())
    assert second.line_id == first.line_id
    assert ledger.invoices[invoice.invoice_id].total_cents == 11000

    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))
    cheaper = _schedules(12000, 8000)
    first = await _build(ledger, credits, cheaper).execute(_cmd())
    second = await _build(ledger, credits, cheaper).execute(_cmd())
    assert second.credit_id == first.credit_id
    assert len(credits.rows) == 1


@pytest.mark.asyncio
async def test_a_second_move_in_the_same_period_is_priced_on_its_own() -> None:
    """A→B then B→C in one month: two distinct keys, two distinct effects."""
    ledger, credits = FakeLedger(), FakeCredits()
    invoice = _invoice()
    ledger.seed(invoice, _line(invoice, 8000))
    schedules = _schedules()
    schedules.rows["sess-c"] = _schedule("sess-c", 4000, (6, 13, 20, 27))
    use_case = _build(ledger, credits, schedules)

    first = await use_case.execute(_cmd())
    second = await use_case.execute(
        _cmd(from_session_id="sess-b", to_session_id="sess-c", effective_at=EFFECTIVE)
    )

    assert first.outcome == "debited" and first.delta_cents == 3000
    assert second.outcome == "credited" and second.delta_cents == -6000
    assert ledger.invoices[invoice.invoice_id].total_cents == 11000
    assert len(credits.rows) == 1


@pytest.mark.asyncio
async def test_effective_period_uses_academy_timezone() -> None:
    """Sept 1 00:30 UTC is still Aug 31 in Chicago → August is the period."""
    ledger, credits = FakeLedger(), FakeCredits()
    august = _invoice("inv-enr-1-2026-08", period="2026-08")
    ledger.seed(august, _line(august, 8000))
    september = _invoice("inv-enr-1-2026-09", period="2026-09")
    ledger.seed(september, _line(september, 8000))
    schedules = FakeSchedules(
        rows={
            "sess-a": MoveSessionSchedule(
                session_id="sess-a", monthly_price_cents=8000, timezone=TZ, occurrences=[]
            ),
            "sess-b": MoveSessionSchedule(
                session_id="sess-b", monthly_price_cents=8000, timezone=TZ, occurrences=[]
            ),
        }
    )

    result = await _build(ledger, credits, schedules).execute(
        _cmd(effective_at=datetime(2026, 9, 1, 0, 30, tzinfo=UTC))
    )

    assert result.effective_period == "2026-08"
    assert result.invoice_id == august.invoice_id


@pytest.mark.asyncio
async def test_void_and_prior_adjustment_invoices_are_not_the_period_invoice() -> None:
    ledger, credits = FakeLedger(), FakeCredits()
    voided = _invoice("inv-void", status="void")
    ledger.seed(voided, _line(voided, 8000))
    prior_adjustment = _invoice("inv-move-prior", total=1000).model_copy(
        update={"source_type": MOVE_SOURCE_TYPE}
    )
    ledger.seed(prior_adjustment)

    result = await _build(ledger, credits, _schedules()).execute(_cmd())

    assert result.outcome == "no_invoice"
