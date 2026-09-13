"""Resolve what a parent needs to recognise an invoice (issue #659).

Lives in ``composition`` for the same reason ``email_adapters`` does: it joins
billing's ledger to the roster collections that belong to other contexts, which
the contexts themselves may not import.

One resolver call answers four questions for one ``invoice_id``:

* **Which child?** — ``invoices.student_id`` → ``students.full_name``.
* **Which class?** — ``invoices.enrollment_id`` → ``enrollments.session_id`` →
  the session's day/time/name.
* **Which number?** — the invoice's own ``invoice_number``, minted lazily here
  for the invoices that predate numbering so a parent never sees the internal
  ``inv-monthly-...`` slug. (Owner decision 2026-09-12: historical invoices
  keep their ids and gain a number on first display or send.)
* **What did they last pay?** — the newest ``payment_allocations`` row against
  another invoice for the same enrollment within 45 days, so back-to-back
  months explain themselves instead of reading as one duplicate charge.

Every lookup is best effort. A resolver that returns partial or empty naming
costs an email its detail; one that raises would cost the family the email,
which is strictly worse than the problem being fixed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.composition.email_adapters import InvoiceNaming, LastCharge
from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.domain.ledger import format_session_label
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

#: How far back a previous charge is still worth naming (issue #659). The
#: incident was two charges five days apart; a charge older than a billing
#: cycle or two explains nothing and only adds noise to the email.
LAST_CHARGE_WINDOW = timedelta(days=45)


def build_invoice_naming_resolver(
    *,
    ledger: Any,
    db: Any,
    billing_counters: Any,
    billing_settings: Any,
    now: Callable[[], datetime] | None = None,
) -> Callable[[str], Awaitable[InvoiceNaming]]:
    _now = now or (lambda: datetime.now(UTC))

    async def resolve(invoice_id: str) -> InvoiceNaming:
        academy_id = current_academy_id()
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None:
            return InvoiceNaming()

        student_name = await _student_name(db, academy_id, invoice.student_id)
        session_label = await _session_label(db, academy_id, invoice.enrollment_id)
        number = invoice.invoice_number or await _lazily_mint(
            db=db,
            invoice=invoice,
            academy_id=academy_id,
            billing_counters=billing_counters,
            billing_settings=billing_settings,
        )
        last_charge = await _last_charge(db, academy_id, invoice, now=_now())
        return InvoiceNaming(
            student_name=student_name,
            session_label=session_label,
            invoice_number=number,
            last_charge=last_charge,
        )

    return resolve


async def _student_name(db: Any, academy_id: str, student_id: str | None) -> str | None:
    if not student_id:
        return None
    doc = await db["students"].find_one(
        {"academy_id": academy_id, "student_id": student_id}, {"full_name": 1}
    )
    return str((doc or {}).get("full_name") or "") or None


async def _session_label(db: Any, academy_id: str, enrollment_id: str | None) -> str | None:
    if not enrollment_id:
        return None
    enrollment = await db["enrollments"].find_one(
        {"academy_id": academy_id, "enrollment_id": enrollment_id}, {"session_id": 1}
    )
    session_id = str((enrollment or {}).get("session_id") or "")
    if not session_id:
        return None
    session = await db["sessions"].find_one(
        {"academy_id": academy_id, "session_id": session_id},
        {"name": 1, "title": 1, "days_of_week": 1, "start_time": 1},
    )
    if session is None:
        return None
    return format_session_label(
        name=str(session.get("name") or session.get("title") or "") or None,
        days_of_week=list(session.get("days_of_week") or []),
        start_time=str(session.get("start_time") or "") or None,
    )


async def _last_charge(
    db: Any, academy_id: str, invoice: Any, *, now: datetime
) -> LastCharge | None:
    """The newest settled charge on the same enrollment, inside the window.

    Issue #659's core ask: "Your last charge was $70.00 for August 2026 tuition
    on September 3" is what turns two charges five days apart from a suspected
    duplicate into two named months.

    The invoice being sent is excluded — a parent reading about September does
    not want September's own allocation quoted back at them — and so is any
    allocation of zero, which is a bookkeeping row rather than money moving.
    Best effort like the rest of this module: a failed lookup drops the
    sentence, never the email.
    """
    enrollment_id = getattr(invoice, "enrollment_id", None)
    if not enrollment_id:
        return None
    try:
        siblings = {
            str(doc.get("invoice_id") or ""): doc
            async for doc in db["invoices"].find(
                {
                    "academy_id": academy_id,
                    "enrollment_id": enrollment_id,
                    "invoice_id": {"$ne": invoice.invoice_id},
                },
                {"invoice_id": 1, "period": 1, "currency": 1},
            )
        }
        siblings.pop("", None)
        if not siblings:
            return None
        allocation = await db["payment_allocations"].find_one(
            {
                "academy_id": academy_id,
                "invoice_id": {"$in": list(siblings)},
                "amount_cents": {"$gt": 0},
                "created_at": {"$gte": now - LAST_CHARGE_WINDOW},
            },
            sort=[("created_at", -1)],
        )
        if allocation is None:
            return None
        paid_invoice = siblings[str(allocation["invoice_id"])]
        created_at = allocation.get("created_at")
        if not isinstance(created_at, datetime):
            return None
        return LastCharge(
            amount_cents=int(allocation.get("amount_cents") or 0),
            currency=str(paid_invoice.get("currency") or "usd"),
            period=str(paid_invoice.get("period") or ""),
            charged_on=created_at.date(),
        )
    except Exception:
        log.warning(
            "invoice_last_charge_unresolved",
            extra={"invoice_id": getattr(invoice, "invoice_id", None)},
            exc_info=True,
        )
        return None


async def _lazily_mint(
    *,
    db: Any,
    invoice: Any,
    academy_id: str,
    billing_counters: Any,
    billing_settings: Any,
) -> str | None:
    """Give a pre-numbering invoice a number the first time it is shown or sent.

    Persisted, not computed on the fly: the same invoice must carry the same
    number in the email, the parent portal and the admin table, and the counter
    is consumed either way.

    Written as a narrow ``$set`` rather than through ``save_invoice`` on
    purpose. ``save_invoice`` is guarded by the optimistic-concurrency
    ``version`` token, and this runs *inside* a send — the caller is holding an
    invoice it is about to hand to ``record_delivery`` and save. Bumping the
    version underneath it would turn every legacy invoice's first send into a
    stale-write conflict: the exact invoices this exists to serve. The filter
    also refuses to overwrite a number, so a concurrent send cannot renumber an
    invoice or collide on the unique ``(academy_id, invoice_number)`` index; if
    it loses that race it reads back and reports the winner's number.
    """
    try:
        number = await mint_invoice_number(
            billing_counters=billing_counters,
            billing_settings=billing_settings,
            academy_id=academy_id,
            period=invoice.period,
        )
        if number is None:
            return None
        result = await db["invoices"].update_one(
            {
                "academy_id": academy_id,
                "invoice_id": invoice.invoice_id,
                "$or": [{"invoice_number": None}, {"invoice_number": {"$exists": False}}],
            },
            {"$set": {"invoice_number": number}},
        )
        if getattr(result, "matched_count", 0):
            return number
        doc = await db["invoices"].find_one(
            {"academy_id": academy_id, "invoice_id": invoice.invoice_id},
            {"invoice_number": 1},
        )
        return str((doc or {}).get("invoice_number") or "") or None
    except Exception:
        log.warning(
            "invoice_number_lazy_mint_failed",
            extra={"invoice_id": invoice.invoice_id},
            exc_info=True,
        )
        return None
