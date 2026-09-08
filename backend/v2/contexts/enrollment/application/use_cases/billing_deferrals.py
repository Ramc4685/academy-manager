"""Enrollment billing deferrals.

Deferrals are the audit trail that explains why monthly billing may skip an
enrollment. New records must be bounded by a resume, review, or expiry date.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

BillingDeferralType = Literal[
    "fixed_pause",
    "admin_pause",
    "manual_skip",
    "capacity_blocked_resume",
    "legacy_skip_period",
]
BillingDeferralStatus = Literal["active", "closed"]


MAX_DEFERRAL_PERIODS = 12


def _next_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    month += 1
    if month > 12:
        year, month = year + 1, 1
    return f"{year:04d}-{month:02d}"


def paused_billing_periods(
    *,
    effective_at: datetime | date,
    resume_on: date | None,
    review_on: date | None,
) -> list[str]:
    """Billing periods a pause suppresses (issue #651).

    The month containing ``effective_at`` stays payable (policy: the current
    month is owed in full). Suppression starts the following month. A month is
    suppressed when the enrollment is still paused on its billing day — the
    same rule the monthly generator applies by status — so a resume on the 1st
    bills that month and a resume later in the month does not (the family gets
    the remainder of that month without a catch-up invoice). An indefinite
    pause bounded only by ``review_on`` suppresses through the review month.
    Capped at ``MAX_DEFERRAL_PERIODS`` months.
    """

    start = effective_at.date() if isinstance(effective_at, datetime) else effective_at
    period = _next_period(start.strftime("%Y-%m"))
    if resume_on is not None:
        resume_period = resume_on.strftime("%Y-%m")
        periods: list[str] = []
        while len(periods) < MAX_DEFERRAL_PERIODS:
            if period > resume_period or (period == resume_period and resume_on.day == 1):
                break
            periods.append(period)
            period = _next_period(period)
        return periods
    if review_on is not None:
        last_inclusive = review_on.strftime("%Y-%m")
        periods = []
        while period <= last_inclusive and len(periods) < MAX_DEFERRAL_PERIODS:
            periods.append(period)
            period = _next_period(period)
        return periods
    return []


class BillingDeferral(BaseModel):
    model_config = {"frozen": True}

    deferral_id: str
    enrollment_id: str
    student_id: str
    deferral_type: BillingDeferralType
    reason: str = ""
    source: str
    source_id: str | None = None
    actor_id: str | None = None
    actor_type: str = "system"
    billing_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    resume_on: date | None = None
    review_on: date | None = None
    expires_on: date | None = None
    status: BillingDeferralStatus = "active"
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    closure_reason: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounded(self) -> BillingDeferral:
        if self.status == "active" and not (self.resume_on or self.review_on or self.expires_on):
            raise ValueError("resume_on, review_on, or expires_on is required")
        return self

    def covers_period(self, period: str, *, today: date) -> bool:
        if self.status != "active":
            return False
        if self.billing_period != period:
            return False
        if self.resume_on is not None and self.resume_on <= today:
            return False
        if self.review_on is not None and self.review_on <= today:
            return False
        if self.expires_on is not None and self.expires_on < today:
            return False
        return True

    @property
    def needs_review(self) -> bool:
        return self.review_on is not None and self.review_on <= date.today()


class BillingDeferralRepository(Protocol):
    async def add(self, deferral: BillingDeferral) -> None: ...

    async def active_for_enrollment_period(
        self,
        *,
        enrollment_id: str,
        period: str,
        today: date,
    ) -> BillingDeferral | None: ...

    async def close_active_for_enrollment(
        self,
        enrollment_id: str,
        *,
        closed_at: datetime,
        closed_by: str,
        reason: str,
    ) -> None: ...

    async def list_admin_warnings(
        self, *, today: date, limit: int = 100
    ) -> list[dict[str, object]]: ...
