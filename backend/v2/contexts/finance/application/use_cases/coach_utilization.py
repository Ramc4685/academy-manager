"""GetCoachUtilization use case — Phase 2 analytics.

Reads each coach's held-class hours and payroll for the requested months via
an injected ``HeldClassReader`` and returns per-coach utilization metrics.

Utilization rate is ``hours / max_hours`` where ``max_hours`` is a soft
cap (default 40 per period, configurable at construction time), rounded
to 4 decimal places and capped at ``Decimal("1.0")``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from backend.v2.contexts.finance.application.ports import (
    HeldClassReader,
    MarkedWithin24hReader,
)

# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------

_FOUR_DP = Decimal("0.0001")
_ONE = Decimal("1.0000")


class CoachUtilizationPoint(BaseModel):
    """Utilization metrics for one coach in one period."""

    model_config = {"frozen": True}

    coach_id: str
    period: str
    hours: Decimal  # hours of held classes (lead or assistant)
    payout_minor: int  # total payout in minor currency units
    utilization_rate: Decimal  # hours / max_hours, 4dp, capped at 1.0
    # Share of this coach's past occurrences (across the requested periods)
    # whose attendance was marked within 24h of the occurrence's end_at.
    # None when no compliance_reader was supplied, or the coach has no
    # marked occurrences yet to compute a rate from (avoids reporting 0/0
    # as 0%, which would misleadingly read as non-compliance).
    compliance_within_24h_rate: Decimal | None = None


class CoachUtilizationResult(BaseModel):
    """Result returned by ``GetCoachUtilization``."""

    model_config = {"frozen": True}

    coaches: list[CoachUtilizationPoint]
    periods: list[str]  # the periods queried
    total_payout_minor: int  # sum of all coach payouts across all periods


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class GetCoachUtilization:
    """Return per-coach utilization metrics for the given academy and periods.

    Args:
        classes: Port that reads each coach's held-class hours per month.
        academy_id: Scopes the query to a single academy.
        max_hours: Soft cap for the utilization rate denominator.  A coach
            with ``hours >= max_hours`` receives a rate of ``1.0``.
            Defaults to 40 (a full-time equivalent month of coaching).
    """

    def __init__(
        self,
        *,
        classes: HeldClassReader,
        academy_id: str,
        max_hours: int = 40,
        compliance_reader: MarkedWithin24hReader | None = None,
    ) -> None:
        self._classes = classes
        self._academy_id = academy_id
        self._max_hours = Decimal(max_hours)
        self._compliance_reader = compliance_reader

    async def execute(self, periods: list[str]) -> CoachUtilizationResult:
        """Return utilization data for the requested periods.

        Args:
            periods: List of opaque period strings (e.g. ``["2026-04", "2026-05"]``).
                An empty list returns an empty result with total_payout_minor 0.

        Returns:
            ``CoachUtilizationResult`` with one ``CoachUtilizationPoint`` per
            (coach, period) pair with held hours or payroll.  Coaches with
            neither in a period do not appear for it.
        """
        if not periods:
            return CoachUtilizationResult(
                coaches=[],
                periods=periods,
                total_payout_minor=0,
            )

        coach_hours = await self._classes.coach_hours_for_periods(
            academy_id=self._academy_id,
            periods=periods,
        )

        compliance_by_coach: dict[str, Decimal | None] = {}
        if self._compliance_reader is not None:
            rows = await self._compliance_reader.compliance_for_periods(
                academy_id=self._academy_id,
                periods=periods,
            )
            for row in rows:
                if row.total_marked_count <= 0:
                    compliance_by_coach[row.coach_id] = None
                else:
                    compliance_by_coach[row.coach_id] = (
                        Decimal(row.marked_within_24h_count) / Decimal(row.total_marked_count)
                    ).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)

        points: list[CoachUtilizationPoint] = []
        total_payout = 0

        for hours_row in coach_hours:
            if hours_row.period not in periods:
                continue  # defensive — reader should already filter

            rate = (hours_row.hours / self._max_hours).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)
            if rate > _ONE:
                rate = _ONE

            points.append(
                CoachUtilizationPoint(
                    coach_id=hours_row.coach_id,
                    period=hours_row.period,
                    hours=hours_row.hours,
                    payout_minor=hours_row.payout_minor,
                    utilization_rate=rate,
                    compliance_within_24h_rate=compliance_by_coach.get(hours_row.coach_id),
                )
            )
            total_payout += hours_row.payout_minor

        return CoachUtilizationResult(
            coaches=points,
            periods=periods,
            total_payout_minor=total_payout,
        )
