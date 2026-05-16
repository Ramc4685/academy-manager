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
    "pending", "succeeded", "failed", "refunded", "partially_refunded", "expired"
]
SubscriptionStatus = Literal["active", "past_due", "cancelled", "incomplete"]


class Payment(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    academy_id: str
    parent_id: str
    # Either tied to a session (one-time checkout) or a subscription.
    session_id: str | None = None
    subscription_id: str | None = None
    stripe_payment_intent_id: str | None = None
    stripe_checkout_session_id: str | None = None
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
    session_id: str | None = None
    stripe_subscription_id: str
    status: SubscriptionStatus = "incomplete"
    payment_mode: Literal["one_time_first_month", "monthly", "manual"] = "monthly"
    created_at: datetime
    updated_at: datetime
