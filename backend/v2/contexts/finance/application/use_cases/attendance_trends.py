"""GetAttendanceTrends use case — Phase 2 analytics.

Reads each requested month's class dates through an injected
``HeldClassReader`` (held, upcoming and cancelled by the shared reporting
definitions, so "completed" here equals month close's held classes),
aggregates per-period totals, and returns trend data for admin dashboards.

The overall completion rate is a weighted average: total_completed across
all periods divided by total_scheduled across all periods (4 decimal
places).  When there are no scheduled occurrences in any period the rate
is 0 rather than a ZeroDivisionError.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from backend.v2.contexts.finance.application.ports import HeldClassReader

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
    cancelled_count: int
    #: held / (scheduled + cancelled), 4dp; 0 when the month has no class dates.
    completion_rate: Decimal


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
        classes: Port that counts each month's class dates.
        academy_id: Scopes the query to a single academy.
    """

    def __init__(
        self,
        *,
        classes: HeldClassReader,
        academy_id: str,
    ) -> None:
        self._classes = classes
        self._academy_id = academy_id

    async def execute(self, periods: list[str]) -> AttendanceTrendsResult:
        """Return trend data for the requested periods.

        Args:
            periods: List of opaque period strings (e.g. ``["2026-04", "2026-05"]``).
                An empty list returns an empty result with overall rate 0.

        Returns:
            ``AttendanceTrendsResult`` with one ``AttendancePeriodPoint`` per
            requested period (in request order).  Periods with no classes
            appear with all counts 0 and completion_rate 0.
        """
        if not periods:
            return AttendanceTrendsResult(
                periods=[],
                overall_completion_rate=Decimal("0"),
            )

        counts = await self._classes.class_counts_for_periods(
            academy_id=self._academy_id,
            periods=periods,
        )

        # Aggregate counts per period (a reader may return several rows each)
        totals: dict[str, dict[str, int]] = {
            p: {"scheduled": 0, "completed": 0, "no_show": 0, "cancelled": 0} for p in periods
        }
        for row in counts:
            if row.period in totals:
                totals[row.period]["scheduled"] += row.scheduled_count
                totals[row.period]["completed"] += row.completed_count
                totals[row.period]["no_show"] += row.no_show_count
                totals[row.period]["cancelled"] += row.cancelled_count

        period_points: list[AttendancePeriodPoint] = []
        grand_scheduled = 0
        grand_completed = 0

        for period in periods:
            sched = totals[period]["scheduled"]
            comp = totals[period]["completed"]
            no_show = totals[period]["no_show"]
            cancelled = totals[period]["cancelled"]
            # Cancelled dates stay in the denominator so the rate shows them.
            dates = sched + cancelled

            if dates == 0:
                rate = Decimal("0")
            else:
                rate = (Decimal(comp) / Decimal(dates)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )

            period_points.append(
                AttendancePeriodPoint(
                    period=period,
                    scheduled_count=sched,
                    completed_count=comp,
                    no_show_count=no_show,
                    cancelled_count=cancelled,
                    completion_rate=rate,
                )
            )
            grand_scheduled += dates
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
