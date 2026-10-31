"""Automated past-due reminders at due+N (issue #774).

The load-bearing assertions are the two the owner's decision turns on: a
reminder fires on the *exact* due+N calendar day (never as a daily drip), and
a second run on the same day sends nothing while a later offset still fires.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.composition.email_adapters import InvoiceNaming, tuition_for, tuition_html
from backend.v2.contexts.billing.application.use_cases.send_past_due_reminders import (
    PastDueInvoice,
    SendPastDueReminders,
)

_TODAY = date(2026, 9, 20)


def _invoice(
    invoice_id: str = "inv-1",
    *,
    due_date: date,
    balance_due_cents: int = 7000,
    reminded_days: tuple[int, ...] = (),
) -> PastDueInvoice:
    return PastDueInvoice(
        invoice_id=invoice_id,
        parent_id="parent-1",
        period="2026-08",
        due_date=due_date,
        balance_due_cents=balance_due_cents,
        reminded_days=reminded_days,
    )


class _FakeInvoices:
    """Stands in for the Mongo reader: all invoices, keyed by due date."""

    def __init__(self, invoices: list[PastDueInvoice]) -> None:
        self.invoices = invoices
        self.queried: list[date] = []

    async def list_past_due(self, *, due_on: date) -> list[PastDueInvoice]:
        self.queried.append(due_on)
        return [inv for inv in self.invoices if inv.due_date == due_on]


class _FakeSender:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, int]] = []

    async def send_past_due_reminder(self, *, invoice: PastDueInvoice, days_past_due: int) -> bool:
        self.sent.append((invoice.invoice_id, days_past_due))
        return self.ok


class _FakeStamps:
    def __init__(self, invoices: _FakeInvoices) -> None:
        self._invoices = invoices
        self.stamps: list[tuple[str, int]] = []

    async def stamp_reminder(self, *, invoice_id: str, days_past_due: int) -> None:
        self.stamps.append((invoice_id, days_past_due))
        self._invoices.invoices = [
            inv.model_copy(update={"reminded_days": (*inv.reminded_days, days_past_due)})
            if inv.invoice_id == invoice_id
            else inv
            for inv in self._invoices.invoices
        ]


def _build(
    invoices: _FakeInvoices, sender: _FakeSender
) -> tuple[SendPastDueReminders, _FakeStamps]:
    stamps = _FakeStamps(invoices)
    return SendPastDueReminders(invoices=invoices, sender=sender, stamps=stamps), stamps


@pytest.mark.asyncio
async def test_sends_at_due_plus_15_and_due_plus_20_only() -> None:
    invoices = _FakeInvoices(
        [
            _invoice("inv-15", due_date=date(2026, 9, 5)),  # due+15 today
            _invoice("inv-20", due_date=date(2026, 8, 31)),  # due+20 today
            _invoice("inv-17", due_date=date(2026, 9, 3)),  # due+17 — not a configured day
        ]
    )
    sender = _FakeSender()
    use_case, _ = _build(invoices, sender)

    result = await use_case.execute(today=_TODAY, reminder_days=(15, 20))

    assert sorted(sender.sent) == [("inv-15", 15), ("inv-20", 20)]
    assert result.sent == 2
    assert invoices.queried == [date(2026, 9, 5), date(2026, 8, 31)]


@pytest.mark.asyncio
async def test_second_run_the_same_day_sends_nothing_but_a_later_offset_still_fires() -> None:
    invoices = _FakeInvoices([_invoice("inv-1", due_date=date(2026, 9, 5))])
    sender = _FakeSender()
    use_case, _ = _build(invoices, sender)

    await use_case.execute(today=_TODAY, reminder_days=(15, 20))
    assert sender.sent == [("inv-1", 15)]

    # Same day again: the stamp makes it a no-op.
    rerun = await use_case.execute(today=_TODAY, reminder_days=(15, 20))
    assert sender.sent == [("inv-1", 15)]
    assert rerun.sent == 0
    assert rerun.already_sent == 1

    # Five days later the same invoice is due+20 — a second, distinct send.
    later = await use_case.execute(today=date(2026, 9, 25), reminder_days=(15, 20))
    assert sender.sent == [("inv-1", 15), ("inv-1", 20)]
    assert later.sent == 1


@pytest.mark.asyncio
async def test_empty_reminder_days_is_the_off_switch() -> None:
    invoices = _FakeInvoices([_invoice("inv-1", due_date=date(2026, 9, 5))])
    sender = _FakeSender()
    use_case, _ = _build(invoices, sender)

    for setting in ((), [], None):
        result = await use_case.execute(today=_TODAY, reminder_days=setting)
        assert result == result.model_copy(update={})
        assert result.sent == 0
    assert sender.sent == []
    assert invoices.queried == []


@pytest.mark.asyncio
async def test_a_failed_send_is_not_stamped_so_the_next_tick_retries() -> None:
    invoices = _FakeInvoices([_invoice("inv-1", due_date=date(2026, 9, 5))])
    sender = _FakeSender(ok=False)
    use_case, stamps = _build(invoices, sender)

    result = await use_case.execute(today=_TODAY, reminder_days=(15,))

    assert result.failed == 1
    assert result.sent == 0
    assert stamps.stamps == []


@pytest.mark.asyncio
async def test_paid_off_invoice_is_skipped() -> None:
    invoices = _FakeInvoices([_invoice("inv-1", due_date=date(2026, 9, 5), balance_due_cents=0)])
    sender = _FakeSender()
    use_case, _ = _build(invoices, sender)

    result = await use_case.execute(today=_TODAY, reminder_days=(15,))

    assert sender.sent == []
    assert result.considered == 0


def test_reminder_copy_names_the_month_in_words_not_the_raw_period() -> None:
    """PR #795's naming helper, reused — never a raw ``2026-09`` in a parent's inbox."""
    naming = InvoiceNaming(student_name="Arjun", session_label="Tue/Thu 5pm")

    subject_lead = tuition_for("2026-09", naming)
    body_lead = tuition_html("2026-09", naming)

    assert subject_lead == "September 2026 tuition for Arjun"
    assert "September 2026" in body_lead
    assert "2026-09" not in subject_lead
    assert "2026-09" not in body_lead
