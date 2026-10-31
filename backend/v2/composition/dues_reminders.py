"""Composition for every "this family owes money" reminder pathway.

Three things are wired here, and they belong together because they share one
email adapter, one pay-link resolver and one view of who is overdue:

* ``send_dues_reminders`` — the admin's manual aggregate send from Payments.
* ``send_past_due_reminders`` — the automated due+N sweep the scheduler drives
  (issue #774). The reader deliberately does NOT filter on ``enrollment_id``:
  the dunning ladder's ``prepare_due_states`` does, which is why manual drafts
  and Mode-B on-the-fly invoices have never been chased at all (lifecycle
  audit, 2026-09-12). Keying on due date + balance reaches them.
* ``count_dunning_alerts`` — the two owner-facing autopay signals on the admin
  home, which previously only ever reached the parent.

Lives outside ``composition/admin.py`` because that module is at its wiring
line budget (``tests/structural/test_composition_is_wiring.py``). Pure wiring:
every collaborator arrives as an argument, and the tenant is resolved from
``current_academy_id()`` at call time, never captured at boot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from backend.v2.composition.email_adapters import DuesReminderEmailAdapter
from backend.v2.composition.invoice_naming import build_invoice_naming_resolver
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    SendDuesReminders,
)
from backend.v2.contexts.billing.application.use_cases.send_past_due_reminders import (
    PastDueInvoice,
    SendPastDueReminders,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.shared.tenancy import current_academy_id

#: Statuses a reminder may chase. ``draft`` is excluded on purpose: an invoice
#: the family has never been sent cannot be "overdue" to them.
_REMINDABLE_STATUSES = ("open", "partially_paid")


@dataclass(frozen=True)
class DuesReminderBundle:
    send_dues_reminders: SendDuesReminders
    send_past_due_reminders: SendPastDueReminders
    count_dunning_alerts: Callable[[], Awaitable[dict[str, int]]]


def compose_dues_reminders(
    db: Any,
    *,
    academies: Any,
    users: Any,
    email_sender: Any,
    email_sender_is_real: bool,
    ledger: Any,
    billing_counters: Any,
    billing_settings: Any,
    parent_payments_link: Callable[[str], Awaitable[tuple[str | None, str]]],
    list_dues_followup: Callable[[], Awaitable[list[dict[str, Any]]]],
    generate_invoice_artifact: Callable[[str, str], Awaitable[dict[str, Any]]],
) -> DuesReminderBundle:
    reminder_email = DuesReminderEmailAdapter(
        academies=academies,
        sender=email_sender,
        # Issue #774: the automated due+N reminder names the tuition month in
        # words, the student and the class through the SAME resolver the
        # invoice emails use (PR #795) — a parent must never read "2026-09".
        naming=build_invoice_naming_resolver(
            ledger=ledger,
            db=db,
            billing_counters=billing_counters,
            billing_settings=billing_settings,
        ),
    )

    async def _parent_recipient(parent_id: str) -> tuple[str, str | None] | None:
        """``(email, display_name)`` for an active parent, else ``None``."""
        membership = await MongoMembershipRepository(db).get_membership(
            current_academy_id(), parent_id
        )
        if membership is None or not membership.is_active() or "parent" not in membership.roles:
            return None
        user = await users.get_by_id(parent_id)
        email = str(user.email if user else "").strip()
        if not email:
            return None
        return email, str(user.display_name if user else "") or None

    # --- the admin's manual aggregate send ---------------------------------

    class _DuesReminderSender:
        async def send_dues_reminders(
            self,
            *,
            parent_ids: list[str] | None,
            generate_invoice_artifacts: bool,
        ) -> dict[str, object]:
            request_academy_id = current_academy_id()
            rows = await list_dues_followup()
            if parent_ids is not None:
                selected = set(parent_ids)
                rows = [row for row in rows if str(row["parent_id"]) in selected]
            generated = 0
            if generate_invoice_artifacts:
                for row in rows:
                    invoice_cursor = (
                        db["invoices"]
                        .find(
                            {
                                "academy_id": request_academy_id,
                                "status": {"$in": ["open", "partially_paid", "draft"]},
                                "balance_due_cents": {"$gt": 0},
                                "$or": [
                                    {"parent_id": row["parent_id"]},
                                    {"parent_user_id": row["parent_id"]},
                                ],
                                "is_deleted": {"$ne": True},
                            }
                        )
                        .sort([("created_at", -1)])
                    )
                    async for invoice in invoice_cursor:
                        await generate_invoice_artifact(
                            str(invoice.get("invoice_id") or invoice.get("invoice_number")),
                            "invoice_pdf",
                        )
                        generated += 1

            if not email_sender_is_real:
                return {
                    "sent": 0,
                    "blocked": True,
                    "reason": (
                        f"Local/test safety block: {len(rows)} reminder(s) were not sent "
                        "(email delivery is not enabled for this environment)."
                    ),
                    "selected_parent_ids": parent_ids or [str(row["parent_id"]) for row in rows],
                    "generated_invoice_artifacts": generated,
                }

            pay_url, _academy_name = await parent_payments_link(request_academy_id)
            sent = 0
            skipped = 0
            for row in rows:
                parent_id = str(row["parent_id"])
                recipient = await _parent_recipient(parent_id)
                if recipient is None:
                    skipped += 1
                    continue
                email, display_name = recipient
                ok = await reminder_email.send_reminder(
                    parent_id=parent_id,
                    email=email,
                    display_name=display_name,
                    total_due_cents=int(row["total_due_cents"]),
                    pending_count=int(row["pending_count"]),
                    currency="usd",
                    pay_url=pay_url,
                )
                if ok:
                    sent += 1
                else:
                    skipped += 1

            reason = (
                f"{skipped} parent(s) skipped (no active membership, no email on file, "
                "or delivery failed)."
                if skipped
                else None
            )
            return {
                "sent": sent,
                "blocked": False,
                "reason": reason,
                "selected_parent_ids": parent_ids or [str(row["parent_id"]) for row in rows],
                "generated_invoice_artifacts": generated,
            }

    # --- the automated due+N sweep (issue #774) ----------------------------

    class _PastDueInvoiceReader:
        async def list_past_due(self, *, due_on: date) -> list[PastDueInvoice]:
            # due_date is persisted as a midnight-UTC instant (see
            # mongo_billing_ledger_repo), so match the whole calendar day.
            start = datetime.combine(due_on, time.min, tzinfo=UTC)
            cursor = db["invoices"].find(
                {
                    "academy_id": current_academy_id(),
                    "status": {"$in": list(_REMINDABLE_STATUSES)},
                    "balance_due_cents": {"$gt": 0},
                    "due_date": {"$gte": start, "$lt": start + timedelta(days=1)},
                    "is_deleted": {"$ne": True},
                },
                {
                    "invoice_id": 1,
                    "parent_id": 1,
                    "parent_user_id": 1,
                    "period": 1,
                    "balance_due_cents": 1,
                    "currency": 1,
                    "reminder_sent_days": 1,
                },
            )
            out: list[PastDueInvoice] = []
            async for doc in cursor:
                parent_id = str(doc.get("parent_id") or doc.get("parent_user_id") or "")
                if not parent_id:
                    continue
                out.append(
                    PastDueInvoice(
                        invoice_id=str(doc["invoice_id"]),
                        parent_id=parent_id,
                        period=str(doc.get("period") or ""),
                        due_date=due_on,
                        balance_due_cents=int(doc.get("balance_due_cents") or 0),
                        currency=str(doc.get("currency") or "usd"),
                        reminded_days=tuple(
                            int(day) for day in (doc.get("reminder_sent_days") or [])
                        ),
                    )
                )
            return out

    class _PastDueReminderSender:
        async def send_past_due_reminder(
            self, *, invoice: PastDueInvoice, days_past_due: int
        ) -> bool:
            if not email_sender_is_real:
                return False
            recipient = await _parent_recipient(invoice.parent_id)
            if recipient is None:
                return False
            email, display_name = recipient
            pay_url, _academy_name = await parent_payments_link(current_academy_id())
            return await reminder_email.send_past_due_reminder(
                parent_id=invoice.parent_id,
                email=email,
                display_name=display_name,
                invoice_id=invoice.invoice_id,
                period=invoice.period,
                balance_due_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                days_past_due=days_past_due,
                pay_url=pay_url,
            )

    class _ReminderStampWriter:
        async def stamp_reminder(self, *, invoice_id: str, days_past_due: int) -> None:
            # ``$addToSet`` is the idempotency key: one email per (invoice,
            # offset), forever. ``last_reminder_at`` is what the Collections
            # rows read, so a chased family shows the automated send too.
            await db["invoices"].update_one(
                {"academy_id": current_academy_id(), "invoice_id": invoice_id},
                {
                    "$addToSet": {"reminder_sent_days": int(days_past_due)},
                    "$set": {"last_reminder_at": datetime.now(UTC)},
                },
            )

    # --- owner-facing autopay signals (issue #774) -------------------------

    async def count_dunning_alerts() -> dict[str, int]:
        """The two autopay signals the owner never saw.

        Both keyed off the dunning ladder's own state so they can never
        disagree with the Payments buckets: a family mid-ladder after at least
        one decline (``active`` with attempts spent), and a family whose ladder
        gave up and had autopay switched off (``dunned``). Counted by family,
        not by invoice — one card failing is one thing to chase.
        """
        request_academy_id = current_academy_id()
        states = db["dunning_states"]
        failed = await states.distinct(
            "parent_id",
            {
                "academy_id": request_academy_id,
                "status": "active",
                "attempt_count": {"$gt": 0},
            },
        )
        exhausted = await states.distinct(
            "parent_id",
            {"academy_id": request_academy_id, "status": "dunned"},
        )
        return {
            "failed_autopay": len(failed),
            "dunning_exhausted": len(exhausted),
        }

    return DuesReminderBundle(
        send_dues_reminders=SendDuesReminders(sender=_DuesReminderSender()),
        send_past_due_reminders=SendPastDueReminders(
            invoices=_PastDueInvoiceReader(),
            sender=_PastDueReminderSender(),
            stamps=_ReminderStampWriter(),
        ),
        count_dunning_alerts=count_dunning_alerts,
    )
