"""Billing domain events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events.base import DomainEvent


class PaymentSucceededPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str | None
    amount_cents: int
    currency: str
    succeeded_at: datetime


class PaymentSucceeded(DomainEvent):
    name: Literal["Billing.PaymentSucceeded"] = "Billing.PaymentSucceeded"
    schema_version: Literal[1] = 1
    payload: PaymentSucceededPayload


class PaymentFailedPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str | None
    reason: str


class PaymentFailed(DomainEvent):
    name: Literal["Billing.PaymentFailed"] = "Billing.PaymentFailed"
    schema_version: Literal[1] = 1
    payload: PaymentFailedPayload


class PaymentRefundedPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    refunded_cents: int
    total_refunded_cents: int
    reason: Literal["admin_initiated", "capacity_failed", "duplicate", "other"]


class PaymentRefunded(DomainEvent):
    name: Literal["Billing.PaymentRefunded"] = "Billing.PaymentRefunded"
    schema_version: Literal[1] = 1
    payload: PaymentRefundedPayload


class CheckoutExpiredPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str | None


class CheckoutExpired(DomainEvent):
    name: Literal["Billing.CheckoutExpired"] = "Billing.CheckoutExpired"
    schema_version: Literal[1] = 1
    payload: CheckoutExpiredPayload


class SubscriptionUpdatedPayload(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    parent_id: str
    status: Literal["active", "past_due", "cancelled", "incomplete"]


class SubscriptionUpdated(DomainEvent):
    name: Literal["Billing.SubscriptionUpdated"] = "Billing.SubscriptionUpdated"
    schema_version: Literal[1] = 1
    payload: SubscriptionUpdatedPayload


class AutopayConsentCapturedPayload(BaseModel):
    model_config = {"frozen": True}

    consent_id: str
    parent_id: str
    method_type: str
    consent_text_version: str
    ach_mandate_version: str | None
    card_disclosure_version: str | None
    source: str
    actor_id: str | None
    captured_at: datetime


class AutopayConsentCaptured(DomainEvent):
    name: Literal["Billing.AutopayConsentCaptured"] = "Billing.AutopayConsentCaptured"
    schema_version: Literal[1] = 1
    payload: AutopayConsentCapturedPayload


class InvoiceLifecyclePayload(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    parent_id: str
    student_id: str | None
    session_type_id: str | None
    billing_period_label: str
    total_cents: int
    stripe_invoice_id: str | None = None


class InvoiceIssued(DomainEvent):
    name: Literal["Billing.InvoiceIssued"] = "Billing.InvoiceIssued"
    schema_version: Literal[1] = 1
    payload: InvoiceLifecyclePayload


class InvoicePaid(DomainEvent):
    name: Literal["Billing.InvoicePaid"] = "Billing.InvoicePaid"
    schema_version: Literal[1] = 1
    payload: InvoiceLifecyclePayload


class InvoiceFailed(DomainEvent):
    name: Literal["Billing.InvoiceFailed"] = "Billing.InvoiceFailed"
    schema_version: Literal[1] = 1
    payload: InvoiceLifecyclePayload


class DunningNoticeRequestedPayload(BaseModel):
    """The "your autopay attempt failed" e-mail, as a durable request.

    Everything the notice renders from is captured here rather than re-read at
    delivery time: the dunning state moves on (another attempt, a terminal
    disable) while the event waits in the outbox, and the parent should receive
    the notice for the attempt that actually failed.
    """

    model_config = {"frozen": True}

    invoice_id: str
    parent_id: str
    period: str
    balance_due_cents: int
    currency: str
    attempt_no: int
    terminal: bool


class DunningNoticeRequested(DomainEvent):
    """Issue #435: the notice used to be one best-effort send inside the dunning
    worker — a failed send was logged and the parent was never told their
    payment failed. Through the outbox it inherits the dispatcher's retry ladder
    and dead-letters if it truly cannot be delivered.
    """

    name: Literal["Billing.DunningNoticeRequested"] = "Billing.DunningNoticeRequested"
    schema_version: Literal[1] = 1
    payload: DunningNoticeRequestedPayload
