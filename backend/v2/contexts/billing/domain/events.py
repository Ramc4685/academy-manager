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
    name: Literal["Billing.PaymentSucceeded"] = "Billing.PaymentSucceeded"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: PaymentSucceededPayload  # type: ignore[assignment]


class PaymentFailedPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str | None
    reason: str


class PaymentFailed(DomainEvent):
    name: Literal["Billing.PaymentFailed"] = "Billing.PaymentFailed"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: PaymentFailedPayload  # type: ignore[assignment]


class PaymentRefundedPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    refunded_cents: int
    total_refunded_cents: int
    reason: Literal["admin_initiated", "capacity_failed", "duplicate", "other"]


class PaymentRefunded(DomainEvent):
    name: Literal["Billing.PaymentRefunded"] = "Billing.PaymentRefunded"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: PaymentRefundedPayload  # type: ignore[assignment]


class CheckoutExpiredPayload(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str | None


class CheckoutExpired(DomainEvent):
    name: Literal["Billing.CheckoutExpired"] = "Billing.CheckoutExpired"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: CheckoutExpiredPayload  # type: ignore[assignment]


class SubscriptionUpdatedPayload(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    parent_id: str
    status: Literal["active", "past_due", "cancelled", "incomplete"]


class SubscriptionUpdated(DomainEvent):
    name: Literal["Billing.SubscriptionUpdated"] = "Billing.SubscriptionUpdated"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: SubscriptionUpdatedPayload  # type: ignore[assignment]


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
    name: Literal["Billing.InvoiceIssued"] = "Billing.InvoiceIssued"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: InvoiceLifecyclePayload  # type: ignore[assignment]


class InvoicePaid(DomainEvent):
    name: Literal["Billing.InvoicePaid"] = "Billing.InvoicePaid"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: InvoiceLifecyclePayload  # type: ignore[assignment]


class InvoiceFailed(DomainEvent):
    name: Literal["Billing.InvoiceFailed"] = "Billing.InvoiceFailed"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: InvoiceLifecyclePayload  # type: ignore[assignment]
