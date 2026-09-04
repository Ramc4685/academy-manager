"""ApplyEnrollmentLifecycle (issue #651): the billing side of cancel/pause/resume."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_lifecycle import (
    ApplyEnrollmentLifecycle,
    ApplyEnrollmentLifecycleCommand,
    period_of,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def _invoice(
    invoice_id: str,
    *,
    period: str,
    status: str = "open",
    total_cents: int = 7000,
    balance_due_cents: int | None = None,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id="parent-1",
        enrollment_id="enr-1",
        period=period,
        status=status,  # type: ignore[arg-type]
        subtotal_cents=total_cents,
        total_cents=total_cents,
        balance_due_cents=total_cents if balance_due_cents is None else balance_due_cents,
        due_date=date(2026, 9, 8),
        created_at=NOW,
        updated_at=NOW,
    )


class FakeLedger:
    def __init__(self, invoices: list[LedgerInvoice]) -> None:
        self.rows = {i.invoice_id: i for i in invoices}

    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[LedgerInvoice]:
        return [i for i in self.rows.values() if i.enrollment_id == enrollment_id]

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self.rows[invoice.invoice_id] = invoice
        return invoice


class FakeAutopay:
    def __init__(self, *, reject: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._reject = reject

    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
        self.calls.append((enrollment_id, status))
        return not self._reject


class FakeDunning:
    def __init__(self) -> None:
        self.suppressed: list[str] = []

    async def suppress_for_invoice(self, *, invoice_id: str, reason: str, now: datetime) -> bool:
        self.suppressed.append(invoice_id)
        return True


def _use_case(ledger: FakeLedger, autopay: FakeAutopay | None = None, dunning=None, tz=None):
    async def _tz() -> str | None:
        return tz

    return ApplyEnrollmentLifecycle(
        ledger=ledger,
        autopay=autopay,
        dunning=dunning,
        academy_timezone=_tz,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_cancel_keeps_current_month_and_voids_later_unpaid_invoices() -> None:
    ledger = FakeLedger(
        [
            _invoice("inv-aug", period="2026-08", status="paid", balance_due_cents=0),
            _invoice("inv-sep", period="2026-09"),
            _invoice("inv-oct", period="2026-10"),
            _invoice("inv-nov", period="2026-11", status="draft"),
        ]
    )
    autopay = FakeAutopay()
    dunning = FakeDunning()
    result = await _use_case(ledger, autopay, dunning).execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1",
            transition="cancelled",
            effective_at=datetime(2026, 9, 15, tzinfo=UTC),
            reason="moving away",
            actor_id="admin-1",
        )
    )

    assert result.effective_period == "2026-09"
    assert result.voided_invoice_ids == ("inv-oct", "inv-nov")
    assert ledger.rows["inv-sep"].status == "open"  # current month stays payable
    assert ledger.rows["inv-oct"].status == "void"
    assert ledger.rows["inv-oct"].void_reason == "moving away"
    assert ledger.rows["inv-oct"].voided_at == NOW
    assert autopay.calls == [("enr-1", "disabled")]
    assert dunning.suppressed == ["inv-oct", "inv-nov"]
    assert result.billing_result == "voided=2,autopay=disabled"


@pytest.mark.asyncio
async def test_future_invoice_with_money_on_it_is_retained_not_voided() -> None:
    ledger = FakeLedger(
        [
            _invoice(
                "inv-oct-partial", period="2026-10", status="partially_paid", balance_due_cents=3000
            ),
            _invoice("inv-oct-credit", period="2026-10", status="open", balance_due_cents=5000),
        ]
    )
    result = await _use_case(ledger, FakeAutopay()).execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1",
            transition="withdrawn",
            effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    assert result.voided_invoice_ids == ()
    assert set(result.retained_invoice_ids) == {"inv-oct-partial", "inv-oct-credit"}
    assert ledger.rows["inv-oct-partial"].status == "partially_paid"
    assert "retained=2" in result.billing_result


@pytest.mark.asyncio
async def test_pause_voids_later_months_and_pauses_autopay() -> None:
    ledger = FakeLedger(
        [_invoice("inv-sep", period="2026-09"), _invoice("inv-oct", period="2026-10")]
    )
    autopay = FakeAutopay()
    result = await _use_case(ledger, autopay).execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1",
            transition="paused",
            effective_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
    )
    assert result.voided_invoice_ids == ("inv-oct",)
    assert ledger.rows["inv-oct"].void_reason == "enrollment_paused"
    assert autopay.calls == [("enr-1", "paused")]


@pytest.mark.asyncio
async def test_resume_voids_nothing_and_reactivates_autopay() -> None:
    ledger = FakeLedger([_invoice("inv-oct", period="2026-10")])
    autopay = FakeAutopay()
    result = await _use_case(ledger, autopay).execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1",
            transition="resumed",
            effective_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
    )
    assert result.voided_invoice_ids == ()
    assert ledger.rows["inv-oct"].status == "open"
    assert autopay.calls == [("enr-1", "active")]
    assert result.billing_result == "autopay_resumed"


@pytest.mark.asyncio
async def test_rejected_autopay_transition_is_reported_not_raised() -> None:
    ledger = FakeLedger([])
    result = await _use_case(ledger, FakeAutopay(reject=True)).execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1", transition="cancelled", effective_at=NOW
        )
    )
    assert result.autopay_applied is False
    assert result.billing_result == "voided=0,autopay=unchanged"


@pytest.mark.asyncio
async def test_effective_period_uses_academy_timezone() -> None:
    # 2026-10-01 03:00 UTC is still 2026-09-30 in Chicago → September is the
    # effective period, so an October invoice is voided.
    ledger = FakeLedger([_invoice("inv-oct", period="2026-10")])
    result = await _use_case(ledger, FakeAutopay(), tz="America/Chicago").execute(
        ApplyEnrollmentLifecycleCommand(
            enrollment_id="enr-1",
            transition="cancelled",
            effective_at=datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
        )
    )
    assert result.effective_period == "2026-09"
    assert result.voided_invoice_ids == ("inv-oct",)


def test_period_of_handles_naive_and_bad_timezone() -> None:
    assert period_of(datetime(2026, 9, 4), None) == "2026-09"
    assert period_of(datetime(2026, 9, 4, tzinfo=UTC), "Not/AZone") == "2026-09"
