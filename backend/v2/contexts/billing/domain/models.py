"""Billing domain models.

Payment aggregate tracks a Stripe payment intent through its lifecycle.
Subscription aggregate tracks recurring billing. Per ADR-0006, academy_id
is on every aggregate but never handled by application code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PaymentStatus = Literal[
    "pending",
    "partially_paid",
    "succeeded",
    "failed",
    "refunded",
    "partially_refunded",
    "expired",
    "waived",
]
SubscriptionStatus = Literal["active", "past_due", "cancelled", "incomplete"]
CreditEntryType = Literal[
    "EARLY_WITHDRAWAL_CREDIT", "MANUAL_CREDIT", "CREDIT_APPLIED", "CREDIT_VOIDED"
]
CreditStatus = Literal["PENDING", "APPROVED", "APPLIED", "EXPIRED", "VOIDED"]
AutopayConsentSource = Literal[
    "parent_checkout_status",
    "stripe_webhook",
    "setup_intent_webhook",
    "invoice_payment_optin",
    "unknown",
]

ALLOWED_PAYMENT_PROJECTION_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"succeeded", "failed", "cancelled"},
    "failed": {"succeeded"},
    "succeeded": {"partially_refunded", "refunded"},
    "partially_refunded": {"refunded"},
    "refunded": set(),
    "cancelled": set(),
}


def can_transition_payment_projection(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in ALLOWED_PAYMENT_PROJECTION_TRANSITIONS.get(current, set())


class Payment(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    academy_id: str
    parent_id: str
    enrollment_id: str | None = None
    # Either tied to a session (one-time checkout) or a subscription.
    session_id: str | None = None
    subscription_id: str | None = None
    stripe_payment_intent_id: str | None = None
    stripe_checkout_session_id: str | None = None
    calculation_snapshot_id: str | None = None
    amount_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    status: PaymentStatus = "pending"
    refunded_cents: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class Subscription(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    academy_id: str
    parent_id: str
    enrollment_id: str | None = None
    session_id: str | None = None
    stripe_subscription_id: str
    stripe_checkout_session_id: str | None = None
    status: SubscriptionStatus = "incomplete"
    payment_mode: Literal["one_time_first_month", "monthly", "manual"] = "monthly"
    created_at: datetime
    updated_at: datetime


class CreditLedgerEntry(BaseModel):
    model_config = {"frozen": True}

    credit_id: str
    academy_id: str
    parent_id: str
    student_id: str | None = None
    enrollment_id: str | None = None
    invoice_id: str | None = None
    type: CreditEntryType
    status: CreditStatus
    amount_cents: int = Field(ge=0)
    remaining_amount_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    reason: str
    source_type: str | None = None
    source_id: str | None = None
    calculation_snapshot_id: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    stripe_credit_note_id: str | None = None
    stripe_customer_balance_txn_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AppliedCreditState(BaseModel):
    """How much account credit an invoice has already consumed (issue #233).

    Derived from ``account_credit_ledger`` — the source of truth, because the
    credit balance decrement and the per-invoice application record are written
    in a single atomic document update. ``credit_applications`` rows and
    ``CREDIT_APPLIED`` entries are projections of that write and can be lost if
    the process dies between the two.

    ``unresolved_credit_ids`` names credits that a) are tagged as applied to the
    invoice but b) carry no recoverable amount anywhere. A caller that is about
    to price an invoice must treat a non-empty tuple as "unknown credit already
    spent" and refuse to bill, rather than billing gross and overcharging.
    """

    model_config = {"frozen": True}

    applied_cents: int = Field(ge=0)
    unresolved_credit_ids: tuple[str, ...] = ()

    @property
    def has_unresolved_drift(self) -> bool:
        return bool(self.unresolved_credit_ids)


class AutopayConsent(BaseModel):
    """Append-only authorization record for saved autopay payment methods."""

    model_config = {"frozen": True}

    consent_id: str
    academy_id: str
    parent_id: str
    enrollment_id: str
    setup_intent_id: str
    checkout_session_id: str | None = None
    stripe_payment_method_id: str
    method_type: str
    consent_text_version: str
    ach_mandate_version: str | None = None
    card_disclosure_version: str | None = None
    source: AutopayConsentSource = "unknown"
    actor_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    captured_at: datetime
    created_at: datetime
