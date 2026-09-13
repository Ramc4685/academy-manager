"""Automated late fees on overdue invoices (issue #552).

``late_fee_cents``/``grace_days`` were editable settings that nothing read.
These tests pin the worker pass that turns them into a real invoice line, and
every skip path that keeps it from charging twice or charging the wrong family.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import AddInvoiceLine
from backend.v2.contexts.billing.application.use_cases.apply_late_fees import (
    LATE_FEE_LINE_TYPE,
    LATE_FEE_SOURCE_TYPE,
    ApplyLateFees,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

ACADEMY_ID = "acad-1"
TODAY = date(2026, 9, 13)
NOW = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)


def _invoice(
    *,
    invoice_id: str = "inv-1",
    status: str = "open",
    due_date: date = TODAY - timedelta(days=10),
    balance_due_cents: int = 10_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=ACADEMY_ID,
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enr-1",
        period="2026-08",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=due_date,
        created_at=NOW,
        updated_at=NOW,
    )


def _late_fee_lines(ledger: _FakeLedger, invoice_id: str = "inv-1") -> list[InvoiceLine]:
    return [ln for ln in ledger.lines.get(invoice_id, []) if ln.line_type == LATE_FEE_LINE_TYPE]


class _FakeLedger:
    """Mirrors the real repo's overdue filter: status allow-list + ``due_date < due_before``."""

    def __init__(self, invoices: list[LedgerInvoice]) -> None:
        self.invoices = {inv.invoice_id: inv for inv in invoices}
        # Seeded like the real store: an invoice's totals are the sum of its
        # lines, so the tuition line that produced subtotal_cents has to be
        # here or add_line would recompute the balance down to just the fee.
        self.lines: dict[str, list[InvoiceLine]] = {
            inv.invoice_id: [
                InvoiceLine(
                    line_id=f"line-tuition-{inv.invoice_id}",
                    academy_id=inv.academy_id,
                    invoice_id=inv.invoice_id,
                    line_type="tuition",
                    description="August tuition",
                    quantity=1,
                    unit_amount_cents=inv.subtotal_cents,
                    amount_cents=inv.subtotal_cents,
                    created_at=NOW,
                )
            ]
            for inv in invoices
        }

    async def list_overdue_invoices(
        self, *, due_before: date, limit: int = 200
    ) -> list[LedgerInvoice]:
        rows = [
            inv
            for inv in self.invoices.values()
            if inv.status in ("open", "partially_paid")
            and inv.balance_due_cents > 0
            and inv.due_date < due_before
        ]
        return sorted(rows, key=lambda inv: (inv.due_date, inv.invoice_id))[:limit]

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return list(self.lines.get(invoice_id, []))

    async def sum_allocations_for_invoice(self, invoice_id: str) -> int:
        return 0

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        stored = invoice.model_copy(update={"version": invoice.version + 1})
        self.invoices[stored.invoice_id] = stored
        return stored

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        self.lines.setdefault(line.invoice_id, []).append(line)
        return line


@dataclass(frozen=True)
class _Fees:
    late_fee_cents: int | None
    grace_days: int | None


class _FakeFeesReader:
    def __init__(self, fees: _Fees) -> None:
        self.fees = fees
        self.calls: list[str] = []

    async def execute(self, academy_id: str) -> _Fees:
        self.calls.append(academy_id)
        return self.fees


class _FakeDunning:
    def __init__(self, active: set[str] | None = None) -> None:
        self.active = active or set()

    async def has_active_retry(self, invoice_id: str) -> bool:
        return invoice_id in self.active


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: list[BillingAuditEntry] = []

    async def append(self, entry: BillingAuditEntry) -> None:
        self.entries.append(entry)


def _build(
    ledger: _FakeLedger,
    *,
    fees: _Fees,
    dunning: _FakeDunning | None = None,
    audit: _FakeAudit | None = None,
) -> tuple[ApplyLateFees, _FakeAudit]:
    audit = audit or _FakeAudit()
    use_case = ApplyLateFees(
        ledger=ledger,
        add_line=AddInvoiceLine(ledger=ledger, clock=lambda: NOW),
        fees=_FakeFeesReader(fees),
        dunning=dunning or _FakeDunning(),
        audit=audit,
        clock=lambda: NOW,
    )
    return use_case, audit


@pytest.mark.asyncio
async def test_overdue_invoice_gets_one_late_fee_line_and_an_audit_entry() -> None:
    ledger = _FakeLedger([_invoice()])
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 1
    assert result.fee_cents_applied == 1_500
    lines = _late_fee_lines(ledger)
    assert len(lines) == 1
    assert lines[0].source_type == LATE_FEE_SOURCE_TYPE
    assert lines[0].amount_cents == 1_500
    assert ledger.invoices["inv-1"].balance_due_cents == 11_500
    assert [e.action for e in audit.entries] == ["late_fee_applied"]
    assert audit.entries[0].invoice_id == "inv-1"
    assert audit.entries[0].before == {"balance_due_cents": 10_000}
    assert audit.entries[0].after == {"balance_due_cents": 11_500}


@pytest.mark.asyncio
async def test_a_second_pass_does_not_charge_the_fee_twice() -> None:
    ledger = _FakeLedger([_invoice()])
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    await use_case.execute(academy_id=ACADEMY_ID)
    second = await use_case.execute(academy_id=ACADEMY_ID)

    assert second.applied == 0
    assert second.skipped_existing == 1
    assert len(_late_fee_lines(ledger)) == 1
    assert len(audit.entries) == 1


@pytest.mark.asyncio
async def test_paid_invoice_is_never_touched() -> None:
    ledger = _FakeLedger([_invoice(status="paid", balance_due_cents=0)])
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 0
    assert _late_fee_lines(ledger) == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_zero_late_fee_is_a_no_op() -> None:
    ledger = _FakeLedger([_invoice()])
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=0, grace_days=0))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    # scanned == 0 proves the overdue query never ran: turning the fee off
    # must cost nothing, not scan every overdue invoice and skip each one.
    assert result.scanned == 0
    assert result.applied == 0
    assert _late_fee_lines(ledger) == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_unset_late_fee_is_a_no_op() -> None:
    ledger = _FakeLedger([_invoice()])
    use_case, _ = _build(ledger, fees=_Fees(late_fee_cents=None, grace_days=None))

    assert (await use_case.execute(academy_id=ACADEMY_ID)).applied == 0
    assert _late_fee_lines(ledger) == []


@pytest.mark.asyncio
async def test_invoice_still_inside_the_grace_period_is_left_alone() -> None:
    # Due five days ago with a five-day grace: today IS the last grace day.
    ledger = _FakeLedger([_invoice(due_date=TODAY - timedelta(days=5))])
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 0
    assert _late_fee_lines(ledger) == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_invoice_inside_the_autopay_retry_ladder_is_skipped() -> None:
    ledger = _FakeLedger([_invoice()])
    use_case, audit = _build(
        ledger,
        fees=_Fees(late_fee_cents=1_500, grace_days=5),
        dunning=_FakeDunning(active={"inv-1"}),
    )

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 0
    assert result.skipped_in_retry == 1
    assert _late_fee_lines(ledger) == []
    assert audit.entries == []


def _seed_line(
    ledger: _FakeLedger,
    *,
    line_type: str,
    description: str,
    invoice_id: str = "inv-1",
) -> None:
    ledger.lines.setdefault(invoice_id, []).append(
        InvoiceLine(
            line_id=f"line-{line_type}-{invoice_id}",
            academy_id=ACADEMY_ID,
            invoice_id=invoice_id,
            line_type=line_type,
            description=description,
            quantity=1,
            unit_amount_cents=0,
            amount_cents=0,
            created_at=NOW,
        )
    )


@pytest.mark.parametrize(
    ("line_type", "description"),
    [
        # What the admin "Add charge" dropdown could actually produce before
        # it offered a `late_fee` option (#552 review).
        ("fee", "Late fee"),
        ("fee", "LATE FEE - August"),
        ("adjustment", "Late charge for August invoice"),
        ("fee", "Late-fee assessed by front desk"),
    ],
)
@pytest.mark.asyncio
async def test_hand_entered_late_fee_under_a_legacy_line_type_suppresses_the_automatic_one(
    line_type: str, description: str
) -> None:
    ledger = _FakeLedger([_invoice()])
    _seed_line(ledger, line_type=line_type, description=description)
    use_case, audit = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 0
    assert result.skipped_existing == 1
    assert _late_fee_lines(ledger) == []
    assert audit.entries == []
    assert ledger.invoices["inv-1"].balance_due_cents == 10_000


@pytest.mark.parametrize(
    ("line_type", "description"),
    [
        # An unrelated fee must not buy the family a free pass on lateness.
        ("fee", "Tournament entry fee"),
        ("adjustment", "Goodwill credit"),
        ("equipment", "Late shipment of restring — replacement grip"),
    ],
)
@pytest.mark.asyncio
async def test_an_unrelated_fee_line_does_not_suppress_the_late_fee(
    line_type: str, description: str
) -> None:
    ledger = _FakeLedger([_invoice()])
    _seed_line(ledger, line_type=line_type, description=description)
    use_case, _ = _build(ledger, fees=_Fees(late_fee_cents=1_500, grace_days=5))

    result = await use_case.execute(academy_id=ACADEMY_ID)

    assert result.applied == 1
    assert len(_late_fee_lines(ledger)) == 1
