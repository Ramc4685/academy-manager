"""SaaS platform billing domain models.

These aggregates describe what CourtMastr charges an academy tenant for using
the SaaS platform. They deliberately do not model parent tuition, students,
enrollments, sessions, invoice allocations, or parent payment credits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PlanStatus = Literal["active", "archived"]
BillingStatus = Literal[
    "trialing",
    "active",
    "past_due",
    "unpaid",
    "incomplete",
    "cancelled",
]
TrialStatus = Literal["none", "active", "expired", "converted"]
CancellationStatus = Literal["none", "scheduled", "cancelled"]


class PlanLimits(BaseModel):
    model_config = {"frozen": True}

    max_active_students: int | None = Field(default=None, ge=0)
    max_locations: int | None = Field(default=None, ge=0)
    max_staff_members: int | None = Field(default=None, ge=0)


class PlatformPlan(BaseModel):
    model_config = {"frozen": True}

    plan_id: str
    code: str
    display_name: str
    monthly_price_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    limits: PlanLimits
    status: PlanStatus = "active"
    stripe_price_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class TenantSubscription(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    academy_id: str
    plan_id: str
    billing_status: BillingStatus
    trial_status: TrialStatus = "none"
    cancellation_status: CancellationStatus = "none"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    cancel_at_period_end: bool = False
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
