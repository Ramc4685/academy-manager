"""Session-type billing domain models.

A ``SessionType`` is a priced billing category (e.g. "Beginner Group",
"Private Lesson"). A ``StudentBillingEnrollment`` records that a student is
actively billed under one session type, optionally backed by a Stripe
subscription. Per ADR-0006, ``academy_id`` is on every aggregate but never
handled by application code.

Note: ``StudentBillingEnrollment`` is deliberately distinct from the
enrollment-context ``Enrollment`` (which models session-roster membership).
This aggregate is the *billing* relationship between a student and a price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.autopay_status import (
    AutopayAttemptOutcome,
    AutopayEnrollmentStatus,
)

BillingPeriodType = Literal["monthly", "per_session"]
StudentBillingEnrollmentStatus = Literal["active", "paused", "cancelled", "transferred_out"]


class SessionType(BaseModel):
    model_config = {"frozen": True}

    session_type_id: str
    academy_id: str
    name: str
    description: str | None = None
    price_cents: int = Field(ge=0)
    billing_period: BillingPeriodType = "monthly"
    overage_rate_cents: int | None = Field(default=None, ge=0)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class StudentBillingEnrollment(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    academy_id: str
    student_id: str
    parent_id: str
    session_type_id: str
    stripe_subscription_id: str | None = None
    billing_start_date: datetime
    status: StudentBillingEnrollmentStatus = "active"
    # Per-enrollment autopay state (Slice B). Independent of `status` (the
    # billing-relationship lifecycle) and of any single charge outcome. This is
    # the single charge-eligibility signal: ChargeInvoiceViaAutopay only charges
    # when autopay_enrollment_status == "active".
    autopay_enrollment_status: AutopayEnrollmentStatus = "not_offered"
    # Projection of the latest charge attempt — orthogonal to enrollment state.
    last_attempt_outcome: AutopayAttemptOutcome | None = None
    last_attempt_at: datetime | None = None
    last_failure_code: str | None = None
    override_price_cents: int | None = Field(default=None, ge=0)
    enrolled_at: datetime
    updated_at: datetime
