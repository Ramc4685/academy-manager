"""GetAttendanceTrends use case — Phase 2 analytics.

Reads ``SessionAttendanceSnapshot`` records for the requested periods via
an injected ``AttendanceSnapshotReader`` port, aggregates per-period
totals across all sessions, and returns trend data for admin dashboards.

The overall completion rate is a weighted average: total_completed across
all periods divided by total_scheduled across all periods (4 decimal
places).  When there are no scheduled occurrences in any period the rate
is 0 rather than a ZeroDivisionError.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from backend.v2.contexts.finance.application.ports import AttendanceSnapshotReader

# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------


class AttendancePeriodPoint(BaseModel):
    """Aggregated attendance totals for one period across all sessions."""

    model_config = {"frozen": True}

    period: str
    scheduled_count: int
    completed_count: int
    no_show_count: int
    completion_rate: Decimal  # 4dp; 0 when scheduled_count == 0


class AttendanceTrendsResult(BaseModel):
    """Trend data returned by ``GetAttendanceTrends``."""

    model_config = {"frozen": True}

    periods: list[AttendancePeriodPoint]
    overall_completion_rate: Decimal  # weighted average across all periods, 4dp


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class GetAttendanceTrends:
    """Return per-period attendance aggregates for the given academy.

    Args:
        snapshot_repo: Port that reads persisted ``SessionAttendanceSnapshot``
            records from the data store.
        academy_id: Scopes the query to a single academy.
    """

    def __init__(
        self,
        *,
        snapshot_repo: AttendanceSnapshotReader,
        academy_id: str,
    ) -> None:
        self._repo = snapshot_repo
        self._academy_id = academy_id

    async def execute(self, periods: list[str]) -> AttendanceTrendsResult:
        """Return trend data for the requested periods.

        Args:
            periods: List of opaque period strings (e.g. ``["2026-04", "2026-05"]``).
                An empty list returns an empty result with overall rate 0.

        Returns:
            ``AttendanceTrendsResult`` with one ``AttendancePeriodPoint`` per
            requested period (in request order).  Periods that have no
            snapshots appear with all counts 0 and completion_rate 0.
        """
        if not periods:
            return AttendanceTrendsResult(
                periods=[],
                overall_completion_rate=Decimal("0"),
            )

        snapshots = await self._repo.list_snapshots_for_periods(
            academy_id=self._academy_id,
            periods=periods,
        )

        # Aggregate counts per period (sum across sessions)
        totals: dict[str, dict[str, int]] = {
            p: {"scheduled": 0, "completed": 0, "no_show": 0} for p in periods
        }
        for snap in snapshots:
            if snap.period in totals:
                totals[snap.period]["scheduled"] += snap.scheduled_count
                totals[snap.period]["completed"] += snap.completed_count
                totals[snap.period]["no_show"] += snap.no_show_count

        period_points: list[AttendancePeriodPoint] = []
        grand_scheduled = 0
        grand_completed = 0

        for period in periods:
            sched = totals[period]["scheduled"]
            comp = totals[period]["completed"]
            no_show = totals[period]["no_show"]

            if sched == 0:
                rate = Decimal("0")
            else:
                rate = (Decimal(comp) / Decimal(sched)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )

            period_points.append(
                AttendancePeriodPoint(
                    period=period,
                    scheduled_count=sched,
                    completed_count=comp,
                    no_show_count=no_show,
                    completion_rate=rate,
                )
            )
            grand_scheduled += sched
            grand_completed += comp

        if grand_scheduled == 0:
            overall_rate = Decimal("0")
        else:
            overall_rate = (Decimal(grand_completed) / Decimal(grand_scheduled)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        return AttendanceTrendsResult(
            periods=period_points,
            overall_completion_rate=overall_rate,
        )
