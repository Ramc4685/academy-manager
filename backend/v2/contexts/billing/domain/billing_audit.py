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
