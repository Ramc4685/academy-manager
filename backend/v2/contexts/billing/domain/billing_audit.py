"""Billing audit trail domain model.

Append-only record of who did what to billing money-movement (refunds, manual payments,
invoice line edits, voids, discounts). Mirrors the payout audit trail so billing has the
same actor/before/after accountability. One document per mutation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

BillingAuditAction = Literal[
    "refund_issued",
    "manual_payment_recorded",
    "invoice_line_added",
    "invoice_line_removed",
    "invoice_voided",
    "discount_set",
    "discount_removed",
    # Charge-routing config, not money movement: flipping the temporary
    # platform-charge fallback changes where money settles, so it gets the
    # same actor/before/after trail.
    "platform_fallback_toggled",
    "admin_charge_initiated",
    "autopay_resumed",
    # Invoicing config, not money movement: billing_day/invoice_due_days decide
    # when invoices are generated and when the dunning ladder's first autopay
    # charge fires, so changes get the same actor/before/after trail.
    "invoice_schedule_changed",
]


class BillingAuditEntry(BaseModel):
    model_config = {"frozen": True}

    audit_id: str
    academy_id: str
    action: BillingAuditAction
    actor_id: str
    at: datetime
    invoice_id: str | None = None
    payment_id: str | None = None
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
