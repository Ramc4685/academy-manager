"""Reporting read-model aggregates (Wave 5A Stream M).

These three snapshots are the stable surface that admin dashboards read.
Computing a snapshot is a write of (academy, period [+ scope]) — never a
write of ad-hoc analytics queries against the live data shapes. Reports
then read snapshots, which makes them cheap, paginatable, and easy to
test.

All three live in the finance context for the same reason ``PayoutPeriod``
does: reporting consumes finance data, and an admin's monthly close
spans revenue, attendance, and coach payout in one workflow. Keeping
them in one context avoids cross-context imports and DTO ping-pong.

``period`` is an opaque string — typically ``YYYY-MM`` for monthly close
but could be ``YYYY-Wnn`` for weekly. The computation use cases convert
it to a concrete ``[start, end)`` window via the caller's policy.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AcademyRevenueSnapshot(BaseModel):
    """Academy-wide revenue for one period.

    Sourced from the billing ledger (invoices + payments + refunds). The
    finance context reads via the ``BillingLedgerReader`` port to avoid
    importing billing internals.
    """

    model_config = {"frozen": True}

    academy_id: str
    period: str
    gross_minor: int = Field(ge=0)
    refunded_minor: int = Field(ge=0)
    outstanding_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    computed_at: datetime

    @property
    def net_minor(self) -> int:
        return self.gross_minor - self.refunded_minor


class SessionAttendanceSnapshot(BaseModel):
    """Attendance counts for one session over one period."""

    model_config = {"frozen": True}

    academy_id: str
    session_id: str
    period: str
    scheduled_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    no_show_count: int = Field(ge=0)
    computed_at: datetime

    @property
    def completion_rate(self) -> Decimal:
        if self.scheduled_count == 0:
            return Decimal("0")
        return (Decimal(self.completed_count) / Decimal(self.scheduled_count)).quantize(
            Decimal("0.0001")
        )


class CoachPayoutSnapshot(BaseModel):
    """Aggregated coach payout for one period.

    Sourced from the durable ``PayoutPeriod`` aggregate (same context, no
    port needed). ``hours`` is a Decimal because a coach may have a
    fractional total across many partial-hour sessions.
    """

    model_config = {"frozen": True}

    academy_id: str
    coach_id: str
    period: str
    hours: Decimal = Field(ge=Decimal("0"))
    payout_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    computed_at: datetime
