"""Automated past-due reminders at due+N days (issue #774).

Until now the only reminder an overdue family could get was one an admin sent
by hand from Payments: the Settings → Notify "Dues reminders" toggle was
persisted and read by nothing, and the scheduler had no past-due job at all.
The owner's decision (2026-09-12) is two automatic emails, at **due+15 and
due+20 days**, both offsets editable in Settings → Billing rules, and an empty
list meaning "send none" — which is why there is no separate on/off flag.

Three properties this use case is built around:

* **Exact-day matching, not "anything older than N".** A reminder fires when
  ``due_date + N == today`` in the academy's calendar, so a family that has
  been overdue for two months gets the two emails its schedule says and never
  a daily drip.
* **Idempotency per (invoice, offset).** Each send stamps the offset on the
  invoice, so a second run on the same day — a redeploy, a retried tick — is
  a no-op, while due+20 still fires five days after due+15 did.
* **No ``enrollment_id`` filter.** The dunning ladder's ``prepare_due_states``
  requires an enrollment id, which is why manual drafts and Mode-B on-the-fly
  invoices are never chased (lifecycle audit, 2026-09-12). This job keys on
  the invoice's own due date and balance, so those invoices are reached too.

The reader, sender and stamp arrive as structural Protocols: nothing here
touches Mongo, and the parent-facing copy lives in the composition adapter.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

from pydantic import BaseModel

log = logging.getLogger(__name__)


class PastDueInvoice(BaseModel):
    """One unpaid invoice, as much as a reminder needs to know about it."""

    model_config = {"frozen": True}

    invoice_id: str
    parent_id: str
    period: str
    due_date: date
    balance_due_cents: int
    currency: str = "usd"
    #: Offsets already emailed for this invoice, so a re-run sends nothing.
    reminded_days: tuple[int, ...] = ()


class PastDueInvoiceReader(Protocol):
    async def list_past_due(self, *, due_on: date) -> list[PastDueInvoice]: ...


class PastDueReminderSender(Protocol):
    async def send_past_due_reminder(
        self, *, invoice: PastDueInvoice, days_past_due: int
    ) -> bool: ...


class ReminderStampWriter(Protocol):
    async def stamp_reminder(self, *, invoice_id: str, days_past_due: int) -> None: ...


class SendPastDueRemindersResult(BaseModel):
    model_config = {"frozen": True}

    considered: int = 0
    sent: int = 0
    already_sent: int = 0
    failed: int = 0


class SendPastDueReminders:
    """Send one reminder per (invoice, configured offset) falling due today."""

    def __init__(
        self,
        *,
        invoices: PastDueInvoiceReader,
        sender: PastDueReminderSender,
        stamps: ReminderStampWriter,
    ) -> None:
        self._invoices = invoices
        self._sender = sender
        self._stamps = stamps

    async def execute(
        self, *, today: date, reminder_days: tuple[int, ...] | list[int] | None
    ) -> SendPastDueRemindersResult:
        offsets = sorted({int(day) for day in (reminder_days or ()) if int(day) > 0})
        if not offsets:
            # Empty is the off switch, not a misconfiguration: say nothing.
            return SendPastDueRemindersResult()

        considered = sent = already = failed = 0
        for offset in offsets:
            due_on = date.fromordinal(today.toordinal() - offset)
            for invoice in await self._invoices.list_past_due(due_on=due_on):
                if invoice.balance_due_cents <= 0:
                    continue
                considered += 1
                if offset in invoice.reminded_days:
                    already += 1
                    continue
                try:
                    ok = await self._sender.send_past_due_reminder(
                        invoice=invoice, days_past_due=offset
                    )
                except Exception:
                    log.warning(
                        "past_due_reminder_send_failed",
                        extra={"invoice_id": invoice.invoice_id, "days_past_due": offset},
                        exc_info=True,
                    )
                    ok = False
                if not ok:
                    failed += 1
                    continue
                # Stamped only after a confirmed send: a family that never got
                # the email must still be reachable on the next tick.
                await self._stamps.stamp_reminder(
                    invoice_id=invoice.invoice_id, days_past_due=offset
                )
                sent += 1

        return SendPastDueRemindersResult(
            considered=considered, sent=sent, already_sent=already, failed=failed
        )
