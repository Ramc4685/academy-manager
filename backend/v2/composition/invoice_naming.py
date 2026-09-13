"""Resolve what a parent needs to recognise an invoice (issue #659).

Lives in ``composition`` for the same reason ``email_adapters`` does: it joins
billing's ledger to the roster collections that belong to other contexts, which
the contexts themselves may not import.

One resolver call answers three questions for one ``invoice_id``:

* **Which child?** — ``invoices.student_id`` → ``students.full_name``.
* **Which class?** — ``invoices.enrollment_id`` → ``enrollments.session_id`` →
  the session's day/time/name.
* **Which number?** — the invoice's own ``invoice_number``, minted lazily here
  for the invoices that predate numbering so a parent never sees the internal
  ``inv-monthly-...`` slug. (Owner decision 2026-09-12: historical invoices
  keep their ids and gain a number on first display or send.)

Every lookup is best effort. A resolver that returns partial or empty naming
costs an email its detail; one that raises would cost the family the email,
which is strictly worse than the problem being fixed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.v2.composition.email_adapters import InvoiceNaming
from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.domain.ledger import format_session_label
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)


def build_invoice_naming_resolver(
    *,
    ledger: Any,
    db: Any,
    billing_counters: Any,
    billing_settings: Any,
) -> Callable[[str], Awaitable[InvoiceNaming]]:
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
        return InvoiceNaming(
            student_name=student_name,
            session_label=session_label,
            invoice_number=number,
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
