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
    # Family billing page: an admin hand-billed one enrollment's month instead of
    # waiting for the monthly generator, creating a real receivable.
    "invoice_hand_billed",
    # Family billing page: an admin opened a blank draft with "Create invoice"
    # and will add the charges by hand (#727).
    "invoice_hand_created",
    "discount_set",
    "discount_removed",
    # Charge-routing config, not money movement: flipping the temporary
    # platform-charge fallback changes where money settles, so it gets the
    # same actor/before/after trail.
    "platform_fallback_toggled",
    "admin_charge_initiated",
    "autopay_resumed",
    # Family billing page: the owner/admin switched autopay OFF for every
    # active enrollment of one parent (spec 2026-09-05-family-billing §5).
    "autopay_paused",
    # Invoicing config, not money movement: billing_day/invoice_due_days decide
    # when invoices are generated and when the dunning ladder's first autopay
    # charge fires, so changes get the same actor/before/after trail.
    "invoice_schedule_changed",
    # Settings -> Billing rules: one owner write that can touch the invoice
    # schedule, the academy late-fee values and the cancellation policy at
    # once. Fee changes were previously unaudited entirely
    # (UpdateAcademyFeesUseCase writes no entry), so this is the trail for
    # them (spec 2026-09-07-billing-rules-design SS4.1).
    "billing_rules_changed",
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
    # Family-level actions (autopay_paused) have no invoice; the family
    # timeline finds them by parent instead.
    parent_id: str | None = None
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
