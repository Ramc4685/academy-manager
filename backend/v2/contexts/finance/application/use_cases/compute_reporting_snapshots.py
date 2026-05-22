"""Snapshot computation use cases for the admin reporting dashboard.

Three use cases — one per snapshot aggregate. Each:

1. Reads the relevant facts via an injected port (billing for revenue,
   session-occurrence reader for attendance, payout period repo for
   coach payout).
2. Builds an immutable snapshot.
3. Upserts it through the snapshot repository (idempotent by natural
   key: (academy_id, period [+ scope])).

The use cases don't pick the date window from ``period`` themselves —
that's the caller's policy (monthly close uses calendar months, etc).
They take ``period_start`` and ``period_end`` explicitly and store
``period`` as an opaque label.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from backend.v2.contexts.finance.application.ports import (
    AcademyRevenueSnapshotRepository,
    BillingLedgerReader,
    CoachPayoutSnapshotRepository,
    PayoutPeriodRepository,
    SessionAttendanceSnapshotRepository,
    SessionOccurrenceReader,
)
from backend.v2.contexts.finance.domain.reporting_snapshots import (
    AcademyRevenueSnapshot,
    CoachPayoutSnapshot,
    SessionAttendanceSnapshot,
)


class ComputeAcademyRevenueSnapshot:
    def __init__(
        self,
        *,
        billing: BillingLedgerReader,
        repository: AcademyRevenueSnapshotRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._billing = billing
        self._repo = repository
        self._clock = clock

    async def execute(
        self,
        *,
        academy_id: str,
        period: str,
        period_start: datetime,
        period_end: datetime,
    ) -> AcademyRevenueSnapshot:
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        totals = await self._billing.revenue_for_period(
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
        )
        snapshot = AcademyRevenueSnapshot(
            academy_id=academy_id,
            period=period,
            gross_minor=totals.gross_minor,
            refunded_minor=totals.refunded_minor,
            outstanding_minor=totals.outstanding_minor,
            currency=totals.currency,
            computed_at=self._clock(),
        )
        return await self._repo.upsert(snapshot)


class ComputeSessionAttendanceSnapshot:
    def __init__(
        self,
        *,
        occurrences: SessionOccurrenceReader,
        repository: SessionAttendanceSnapshotRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._occurrences = occurrences
        self._repo = repository
        self._clock = clock

    async def execute(
        self,
        *,
        academy_id: str,
        session_id: str,
        period: str,
        period_start: datetime,
        period_end: datetime,
    ) -> SessionAttendanceSnapshot:
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        counts = await self._occurrences.counts_for_session(
            academy_id=academy_id,
            session_id=session_id,
            period_start=period_start,
            period_end=period_end,
        )
        snapshot = SessionAttendanceSnapshot(
            academy_id=academy_id,
            session_id=session_id,
            period=period,
            scheduled_count=counts.scheduled_count,
            completed_count=counts.completed_count,
            no_show_count=counts.no_show_count,
            computed_at=self._clock(),
        )
        return await self._repo.upsert(snapshot)


class ComputeCoachPayoutSnapshot:
    """Aggregates persisted ``PayoutPeriod`` rows into a reporting snapshot.

    Unlike the other two, this one reads from within the finance context
    (the ``PayoutPeriodRepository``) — no external port needed.
    """

    def __init__(
        self,
        *,
        payout_periods: PayoutPeriodRepository,
        repository: CoachPayoutSnapshotRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._periods = payout_periods
        self._repo = repository
        self._clock = clock

    async def execute(
        self,
        *,
        academy_id: str,
        coach_id: str,
        period: str,
        period_start: datetime,
        period_end: datetime,
    ) -> CoachPayoutSnapshot:
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")
        # We look up the persisted period for this exact window.
        existing = await self._periods.find_by_window(
            coach_id=coach_id,
            period_start=period_start,
            period_end=period_end,
        )
        if existing is None:
            hours = Decimal("0")
            payout_minor = 0
            currency = "USD"
        else:
            minutes_total = sum((line.minutes for line in existing.lines), Decimal("0"))
            hours = (minutes_total / Decimal(60)).quantize(Decimal("0.0001"))
            payout_minor = existing.total_minor
            currency = existing.currency
        snapshot = CoachPayoutSnapshot(
            academy_id=academy_id,
            coach_id=coach_id,
            period=period,
            hours=hours,
            payout_minor=payout_minor,
            currency=currency,
            computed_at=self._clock(),
        )
        return await self._repo.upsert(snapshot)
