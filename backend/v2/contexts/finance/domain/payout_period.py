"""Finance context — persisted payout period aggregate (Wave 5A Stream J).

Wave 4 introduced ``ComputeCoachPayout`` in the coaching context, which
returns an in-memory ``PayoutStatement``. That statement is computed fresh
every time, which is fine for "preview my next payout" UX but is not a
durable record of "what we paid Coach A in May".

The finance context owns the durable record. A ``PayoutPeriod`` is the
snapshot for one coach over one date window. It has a small state machine:

    draft  --approve()-->  approved  --mark_paid()-->  paid

Once snapshotted, the lines are frozen — re-running compute does NOT
re-write an approved or paid period. That keeps payroll audits sane.

Why this lives in finance, not coaching:

- Coaching owns the calculation function (rates + attribution math).
- Finance owns the persisted artifact (the period + lines + audit state).
- Reporting (also in finance, see ``reporting_snapshots.py``) reads from
  the persisted periods. Cross-context imports stay zero because the
  coaching-context types are re-shaped into local DTOs at the composition
  layer.

All amounts are stored in minor currency units. ``period_start`` is
inclusive, ``period_end`` is exclusive — same convention as
``PayoutStatement``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PayoutPeriodStatus = Literal["draft", "approved", "paid"]
PayoutLineBasis = Literal["scheduled", "substitute", "actual"]


class PersistedPayoutLine(BaseModel):
    """One paid occurrence snapshotted onto a payout period.

    Mirrors ``coaching.PayoutLine`` but is owned by finance and serialised
    in the period's storage. The ``rate_id`` is a *snapshot* — if the
    coach's rate sheet changes after the period is generated, the period
    still reflects what was paid.
    """

    model_config = {"frozen": True}

    occurrence_id: str
    coach_id: str
    basis: PayoutLineBasis
    minutes: Decimal
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    rate_id: str


class PayoutPeriod(BaseModel):
    """A coach's payout for one period, durable.

    The unique key is ``(academy_id, coach_id, period_start, period_end)``
    — re-running generation for the same window is idempotent and returns
    the existing record rather than creating a duplicate.
    """

    model_config = {"frozen": True}

    period_id: str
    academy_id: str
    coach_id: str
    period_start: datetime
    period_end: datetime
    status: PayoutPeriodStatus = "draft"
    currency: str = Field(min_length=3, max_length=3)
    total_minor: int = Field(ge=0)
    lines: list[PersistedPayoutLine] = Field(default_factory=list)
    unpaid_occurrence_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    approved_at: datetime | None = None
    paid_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_window_and_totals(self) -> PayoutPeriod:
        if self.period_end <= self.period_start:
            raise ValueError("PayoutPeriod.period_end must be after period_start")
        summed = sum(line.amount_minor for line in self.lines)
        if summed != self.total_minor:
            raise ValueError(
                f"PayoutPeriod.total_minor ({self.total_minor}) does not "
                f"match sum of lines ({summed})"
            )
        if self.status == "approved" and self.approved_at is None:
            raise ValueError("PayoutPeriod.approved_at required when status=approved")
        if self.status == "paid":
            if self.approved_at is None:
                raise ValueError("PayoutPeriod.approved_at required when status=paid")
            if self.paid_at is None:
                raise ValueError("PayoutPeriod.paid_at required when status=paid")
        return self


class PayoutPeriodStateError(Exception):
    """Raised when a state transition is illegal (e.g. approve a paid period)."""


def approve(period: PayoutPeriod, *, at: datetime) -> PayoutPeriod:
    """Return a new ``PayoutPeriod`` with status=approved.

    Idempotent: approving an already-approved period returns it unchanged.
    Approving a paid period raises ``PayoutPeriodStateError``.
    """
    if period.status == "approved":
        return period
    if period.status == "paid":
        raise PayoutPeriodStateError(
            f"cannot approve payout period {period.period_id!r} in status 'paid'"
        )
    return period.model_copy(update={"status": "approved", "approved_at": at})


def mark_paid(period: PayoutPeriod, *, at: datetime) -> PayoutPeriod:
    """Return a new ``PayoutPeriod`` with status=paid.

    Idempotent: marking an already-paid period returns it unchanged.
    Marking a draft period as paid raises ``PayoutPeriodStateError`` — a
    period must be approved first.
    """
    if period.status == "paid":
        return period
    if period.status == "draft":
        raise PayoutPeriodStateError(
            f"cannot mark payout period {period.period_id!r} paid from status 'draft'"
        )
    return period.model_copy(update={"status": "paid", "paid_at": at})
