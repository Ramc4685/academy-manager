"""Unit tests for the post-generation invoice email pass (issue #430)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.send_generated_invoices import (
    SendGeneratedInvoices,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

NOW = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


def _invoice(
    invoice_id: str,
    *,
    enrollment_id: str | None = "enr-1",
    balance_due_cents: int = 12_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="par-1",
        student_id="stu-1",
        enrollment_id=enrollment_id,
        period="2026-09",
        subtotal_cents=balance_due_cents,
        total_cents=balance_due_cents,
        balance_due_cents=balance_due_cents,
        due_date=date(2026, 9, 10),
        created_at=NOW,
        updated_at=NOW,
    )


class _FakeLedger:
    def __init__(self, invoices: list[LedgerInvoice]) -> None:
        self._invoices = invoices
        self.calls: list[tuple[str, int]] = []

    async def list_undelivered_invoices_for_period(
        self, period: str, *, limit: int = 100
    ) -> list[LedgerInvoice]:
        self.calls.append((period, limit))
        return self._invoices[:limit]


class _FakeAutopay:
    def __init__(self, statuses: dict[str, str | None]) -> None:
        self._statuses = statuses

    async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None:
        return self._statuses.get(enrollment_id)


class _RecordingSender:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.sent: list[str] = []
        self._fail_for = fail_for or set()

    async def __call__(self, invoice_id: str) -> dict[str, str]:
        self.sent.append(invoice_id)
        if invoice_id in self._fail_for:
            raise RuntimeError("resend is down")
        return {"invoice_id": invoice_id}


@pytest.mark.asyncio
async def test_emails_every_undelivered_invoice_for_the_period() -> None:
    ledger = _FakeLedger([_invoice("inv-1"), _invoice("inv-2")])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(ledger=ledger, send=sender).execute("2026-09")

    assert sender.sent == ["inv-1", "inv-2"]
    assert (result.considered, result.emailed, result.email_failed) == (2, 2, 0)
    assert ledger.calls == [("2026-09", 500)]


@pytest.mark.asyncio
async def test_skips_invoices_that_autopay_will_charge() -> None:
    """Emailing a pay link for an invoice the autopay worker is about to
    charge invites the parent to pay it twice."""
    ledger = _FakeLedger(
        [
            _invoice("inv-autopay", enrollment_id="enr-auto"),
            _invoice("inv-manual", enrollment_id="enr-manual"),
        ]
    )
    autopay = _FakeAutopay({"enr-auto": "active", "enr-manual": "paused"})
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(ledger=ledger, autopay=autopay, send=sender).execute(
        "2026-09"
    )

    assert sender.sent == ["inv-manual"]
    assert result.skipped_autopay == 1
    assert result.emailed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paused", "disabled", "offered", "setup_started", None])
async def test_only_an_active_autopay_enrollment_is_skipped(status: str | None) -> None:
    """Every non-active state still needs a human to pay, so it still needs
    the email."""
    ledger = _FakeLedger([_invoice("inv-1", enrollment_id="enr-1")])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(
        ledger=ledger, autopay=_FakeAutopay({"enr-1": status}), send=sender
    ).execute("2026-09")

    assert result.emailed == 1
    assert result.skipped_autopay == 0


@pytest.mark.asyncio
async def test_invoice_without_enrollment_is_emailed() -> None:
    """The autopay charge path fails closed on a missing enrollment_id, so
    such an invoice can only ever be paid by hand."""
    ledger = _FakeLedger([_invoice("inv-1", enrollment_id=None)])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(
        ledger=ledger, autopay=_FakeAutopay({}), send=sender
    ).execute("2026-09")

    assert sender.sent == ["inv-1"]
    assert result.emailed == 1


@pytest.mark.asyncio
async def test_one_failing_invoice_does_not_stop_the_rest() -> None:
    ledger = _FakeLedger([_invoice("inv-1"), _invoice("inv-boom"), _invoice("inv-3")])
    sender = _RecordingSender(fail_for={"inv-boom"})

    result = await SendGeneratedInvoices(ledger=ledger, send=sender).execute("2026-09")

    assert sender.sent == ["inv-1", "inv-boom", "inv-3"]
    assert (result.emailed, result.email_failed) == (2, 1)


@pytest.mark.asyncio
async def test_autopay_lookup_failure_falls_back_to_emailing() -> None:
    """A parent wrongly emailed an invoice they were also charged for can ask
    for a refund; a parent silently emailed nothing is the bug being fixed."""

    class _BrokenAutopay:
        async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None:
            raise RuntimeError("mongo blip")

    ledger = _FakeLedger([_invoice("inv-1")])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(
        ledger=ledger, autopay=_BrokenAutopay(), send=sender
    ).execute("2026-09")

    assert result.emailed == 1
    assert result.skipped_autopay == 0


@pytest.mark.asyncio
async def test_a_full_page_is_reported_as_truncated() -> None:
    ledger = _FakeLedger([_invoice(f"inv-{n}") for n in range(3)])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(ledger=ledger, send=sender).execute("2026-09", limit=3)

    assert result.considered == 3
    assert result.truncated is True


@pytest.mark.asyncio
async def test_nothing_to_send_is_a_clean_no_op() -> None:
    ledger = _FakeLedger([])
    sender = _RecordingSender()

    result = await SendGeneratedInvoices(ledger=ledger, send=sender).execute("2026-09")

    assert sender.sent == []
    assert (result.considered, result.emailed, result.truncated) == (0, 0, False)
