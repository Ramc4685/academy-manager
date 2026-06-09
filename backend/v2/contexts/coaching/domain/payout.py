"""Coach payout domain (Wave 4A).

Three frozen aggregates:

- ``CoachRate``: a versioned per-coach rate sheet entry. Rates are immutable
  once superseded; a new effective rate is a new row with a non-overlapping
  ``effective_from``.
- ``PayoutLine``: one line per paid occurrence on a coach's statement.
- ``PayoutStatement``: the aggregate result of running payout for a coach
  over a date range, plus a list of occurrence ids that were eligible (in
  range, completed, payable, attributed to this coach) but had no matching
  rate. Surfacing those keeps the math auditable.

All amounts are stored in **minor currency units** (e.g. cents) to keep
arithmetic in ``int`` space; division for proration uses ``Decimal`` and
rounds half-even before being cast back to ``int``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CoachRateBillingUnit = Literal["per_session", "per_hour", "percent_of_revenue"]
CoachRateStatus = Literal["active", "superseded"]
PayoutBasis = Literal["scheduled", "substitute", "actual", "lead", "assistant"]
PayableOccurrenceStatus = Literal["scheduled", "cancelled", "completed"]


class CoachAttendanceForPayout(BaseModel):
    """Payroll attendance projection attached to a payable occurrence."""

    model_config = {"frozen": True}

    coach_id: str
    status: Literal["present", "absent"]
    role: Literal["lead", "assistant"] = "lead"
    rate_override_minor: int | None = Field(default=None, ge=0)


class PayableOccurrence(BaseModel):
    """Coaching-context view of a session occurrence used for payout.

    A deliberately minimal projection of ``enrollment.SessionOccurrence`` —
    the coaching context never imports from enrollment (ADR-0005, rule 5).
    Adapters in the composition layer translate from the canonical
    occurrence row to this DTO.
    """

    model_config = {"frozen": True}

    occurrence_id: str
    academy_id: str
    start_at: datetime
    end_at: datetime
    status: PayableOccurrenceStatus
    scheduled_coach_id: str
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    is_payable: bool = True
    coach_attendance: list[CoachAttendanceForPayout] = Field(default_factory=list)
    expected_revenue_minor: int | None = Field(default=None, ge=0)
    """Expected revenue for this occurrence (session price x enrolled
    students), used as the basis for ``percent_of_revenue`` rates. ``None``
    when the session has no price configured."""

    @model_validator(mode="after")
    def _end_after_start(self) -> PayableOccurrence:
        if self.end_at <= self.start_at:
            raise ValueError("PayableOccurrence end_at must be after start_at")
        return self


class CoachRate(BaseModel):
    """A versioned rate sheet entry for one coach.

    Effective window is ``[effective_from, effective_until)``. ``None`` for
    ``effective_until`` means "currently in effect".
    """

    model_config = {"frozen": True}

    rate_id: str
    academy_id: str
    coach_id: str
    billing_unit: CoachRateBillingUnit
    amount_minor: int = Field(ge=0)
    percent_bps: int | None = Field(default=None, ge=0, le=10000)
    """Coach share in basis points (6000 = 60%) for ``percent_of_revenue``."""
    currency: str = Field(min_length=3, max_length=3)
    effective_from: datetime
    effective_until: datetime | None = None
    status: CoachRateStatus = "active"

    @model_validator(mode="after")
    def _window_is_sane(self) -> CoachRate:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("CoachRate.effective_until must be > effective_from")
        if self.billing_unit == "percent_of_revenue" and self.percent_bps is None:
            raise ValueError("CoachRate.percent_bps is required for percent_of_revenue rates")
        return self


class PayoutLine(BaseModel):
    """One paid occurrence on a coach's statement."""

    model_config = {"frozen": True}

    occurrence_id: str
    coach_id: str
    basis: PayoutBasis
    minutes: Decimal
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    rate_id: str
    percent_bps: int | None = Field(default=None, ge=0, le=10000)
    expected_revenue_minor: int | None = Field(default=None, ge=0)


class PayoutStatement(BaseModel):
    """A coach's computed payout for a period.

    ``unpaid_occurrence_ids`` lists occurrences that were attributed to this
    coach and otherwise eligible but had no matching rate at occurrence
    ``start_at``. They are reported, not silently dropped.
    """

    model_config = {"frozen": True}

    coach_id: str
    academy_id: str
    period_start: datetime
    period_end: datetime
    currency: str = Field(min_length=3, max_length=3)
    lines: list[PayoutLine] = Field(default_factory=list)
    total_minor: int = Field(ge=0)
    unpaid_occurrence_ids: list[str] = Field(default_factory=list)
    absent_occurrence_ids: list[str] = Field(default_factory=list)
    """Occurrences attributed to this coach but unpaid because the coach
    was marked absent. Reported separately so payslips can show why."""

    @model_validator(mode="after")
    def _total_matches_lines(self) -> PayoutStatement:
        summed = sum(line.amount_minor for line in self.lines)
        if summed != self.total_minor:
            raise ValueError(
                f"PayoutStatement.total_minor ({self.total_minor}) does not "
                f"match sum of lines ({summed})"
            )
        return self
