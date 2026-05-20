"""Billing proration domain policy.

The policy is intentionally pure: it receives occurrences and returns an
auditable quote. Repositories, BFFs, and Stripe adapters do not calculate
tuition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


ClassStatus = Literal["scheduled", "completed", "canceled", "makeup", "holiday"]
SnapshotStatus = Literal["OPEN", "CONSUMED", "EXPIRED", "SUPERSEDED"]


class BillingPeriod(BaseModel):
    model_config = {"frozen": True}

    label: str = Field(pattern=r"^\d{4}-\d{2}$")
    start_at: datetime
    end_at: datetime
    timezone: str

    @classmethod
    def from_label(cls, label: str, *, timezone_name: str) -> "BillingPeriod":
        year, month = [int(part) for part in label.split("-")]
        tz = ZoneInfo(timezone_name)
        start = datetime(year, month, 1, 0, 0, tzinfo=tz)
        if month == 12:
            end = datetime(year + 1, 1, 1, 0, 0, tzinfo=tz)
        else:
            end = datetime(year, month + 1, 1, 0, 0, tzinfo=tz)
        return cls(label=label, start_at=start, end_at=end, timezone=timezone_name)


class ClassOccurrence(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    start_at: datetime
    end_at: datetime
    status: ClassStatus
    is_billable: bool
    timezone: str


class BillingCalculationSnapshot(BaseModel):
    model_config = {"frozen": True}

    snapshot_id: str | None = None
    parent_snapshot_id: str | None = None
    status: SnapshotStatus = "OPEN"
    calculation_type: str = "FIRST_MONTH_PRORATION"
    monthly_price_cents: int
    discount_cents: int = 0
    billing_period_start: datetime
    billing_period_end: datetime
    billing_period_label: str
    timezone: str
    total_eligible_classes: int
    billable_remaining_classes: int
    proration_ratio: str
    final_amount_cents: int
    rounding_mode: str = "HALF_UP_FINAL_CENT"
    included_occurrence_ids: list[str]
    excluded_occurrences: dict[str, str]
    policy_version: str = "first-month-proration-v1"
    settings_version: str = "billing-settings-v1"
    schedule_signature: str | None = None
    override_reason: str | None = None
    expires_at: datetime | None = None
    calculated_at: datetime
    calculated_by: str


def schedule_signature(occurrences: list[ClassOccurrence], *, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    payload = [
        {
            "occurrence_id": occurrence.occurrence_id,
            "status": occurrence.status,
            "start_at": occurrence.start_at.astimezone(tz).isoformat(),
            "is_billable": occurrence.is_billable,
        }
        for occurrence in sorted(occurrences, key=lambda o: o.occurrence_id)
    ]
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FirstMonthProrationPolicy:
    cutoff_hours: int = 2

    def quote(
        self,
        *,
        monthly_price_cents: int,
        discount_cents: int,
        period: BillingPeriod,
        occurrences: list[ClassOccurrence],
        billing_start_at: datetime,
        calculated_at: datetime,
        calculated_by: str,
    ) -> BillingCalculationSnapshot:
        eligible = [
            occurrence
            for occurrence in sorted(occurrences, key=lambda o: o.occurrence_id)
            if self._is_eligible(occurrence, period)
        ]
        included: list[str] = []
        excluded: dict[str, str] = {}
        for occurrence in eligible:
            if occurrence.start_at < billing_start_at:
                excluded[occurrence.occurrence_id] = "BEFORE_BILLING_START"
                continue
            if occurrence.start_at < calculated_at:
                excluded[occurrence.occurrence_id] = "ELAPSED_BEFORE_ENROLLMENT"
                continue
            seconds_until_class = (occurrence.start_at - calculated_at).total_seconds()
            if seconds_until_class < self.cutoff_hours * 3600:
                excluded[occurrence.occurrence_id] = "SAME_DAY_CUTOFF"
                continue
            included.append(occurrence.occurrence_id)

        total = len(eligible)
        remaining = len(included)
        amount = 0
        if total > 0 and remaining > 0:
            base_after_discount = max(monthly_price_cents - discount_cents, 0)
            amount = _round_half_up_rational(base_after_discount * remaining, total)
        ratio = f"{remaining}/{total}" if total else "0/0"
        return BillingCalculationSnapshot(
            monthly_price_cents=monthly_price_cents,
            discount_cents=discount_cents,
            billing_period_start=period.start_at,
            billing_period_end=period.end_at,
            billing_period_label=period.label,
            timezone=period.timezone,
            total_eligible_classes=total,
            billable_remaining_classes=remaining,
            proration_ratio=ratio,
            final_amount_cents=amount,
            included_occurrence_ids=included,
            excluded_occurrences=excluded,
            schedule_signature=schedule_signature(eligible, timezone_name=period.timezone),
            calculated_at=calculated_at,
            calculated_by=calculated_by,
        )

    @staticmethod
    def _is_eligible(occurrence: ClassOccurrence, period: BillingPeriod) -> bool:
        local_start = occurrence.start_at.astimezone(ZoneInfo(period.timezone))
        if not (period.start_at <= local_start < period.end_at):
            return False
        return occurrence.is_billable and occurrence.status in {"scheduled", "completed", "makeup"}


def _round_half_up_rational(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    quotient, remainder = divmod(numerator, denominator)
    return quotient + (1 if remainder * 2 >= denominator else 0)
