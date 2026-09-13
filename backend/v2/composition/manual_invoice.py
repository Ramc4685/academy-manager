"""The Family billing page's "Create invoice" action (#727).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget (``test_composition_is_wiring`` is the check) — same reasoning as
``composition/enrollment_holds.py``.

Two defects this module exists to fix, both against the inline closure that
used to do this in ``admin.py``:

* the idempotency key was ``admin-invoice-{invoice_id}`` where ``invoice_id``
  was a ULID minted inside the same call, so the ledger repo's de-dup lookup
  could never match and a double-click (or a retried request after a network
  blip) left two blank drafts on the family. The key now comes from inputs the
  caller can repeat — the parent and the client's request id.
* nothing was appended to the billing audit trail, so neither the family
  timeline nor the invoice audit drawer showed who created a manual invoice —
  unlike "Bill this month" right next to it, which writes ``invoice_hand_billed``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.invoice_due_date import (
    resolve_invoice_due_date,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.shared.ids import new_ulid


async def create_manual_invoice(
    *,
    ledger: Any,
    settings_repo: Any,
    audit_log: Any,
    academy_id: str,
    student_id: str,
    parent_id: str,
    period: str,
    due_date: date | None,
    enrollment_id: str | None,
    actor_id: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Open one blank draft for a student, once per client submit, audited."""
    now = datetime.now(UTC)
    resolved_due_date = await resolve_invoice_due_date(
        settings_repo, due_date=due_date, today=now.date()
    )
    invoice_id = f"inv-{new_ulid()}"
    invoice = LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=academy_id,
        parent_id=parent_id,
        student_id=student_id,
        enrollment_id=enrollment_id,
        period=period,
        status="draft",
        subtotal_cents=0,
        discount_cents=0,
        total_cents=0,
        balance_due_cents=0,
        currency="usd",
        due_date=resolved_due_date,
        created_at=now,
        updated_at=now,
    )
    # A retry of the same dialog submit carries the same request id, so the
    # repo's idempotency lookup returns the first draft instead of inserting a
    # second one. Callers with no request id (the use case's direct callers,
    # and any client from before this shipped) keep the old create-every-time
    # behaviour: there is nothing stable to key on.
    key = f"admin-invoice-{parent_id}-{request_id}" if request_id else f"admin-invoice-{invoice_id}"
    created = await ledger.create_invoice(invoice, lines=[], idempotency_key=key)
    if created.invoice_id != invoice_id:
        # De-duplicated onto an earlier draft: that one already has its audit
        # row, and the trail is append-only, so do not write a second one.
        return dict(created.model_dump(mode="json"))
    await audit_log.append(
        BillingAuditEntry(
            audit_id=f"baud-{new_ulid()}",
            academy_id=academy_id,
            action="invoice_hand_created",
            actor_id=actor_id or "system",
            at=now,
            invoice_id=created.invoice_id,
            parent_id=parent_id,
            reason=period,
            after={
                "student_id": student_id,
                "enrollment_id": enrollment_id,
                "period": period,
                "status": created.status,
            },
        )
    )
    return dict(created.model_dump(mode="json"))
