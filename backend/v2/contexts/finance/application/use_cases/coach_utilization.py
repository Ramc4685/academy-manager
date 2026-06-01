"""GetCoachUtilization use case — Phase 2 analytics.

Reads ``CoachPayoutSnapshot`` records for the requested periods via an
injected ``CoachPayoutSnapshotReader`` port and returns per-coach
utilization metrics.

Utilization rate is ``hours / max_hours`` where ``max_hours`` is a soft
cap (default 40 per period, configurable at construction time), rounded
to 4 decimal places and capped at ``Decimal("1.0")``.

``CoachPayoutSnapshot`` has no raw session count field — the domain
aggregate stores ``hours`` and ``payout_minor``.  The use case therefore
reports ``hours`` directly and derives a utilization rate from it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from backend.v2.contexts.finance.application.ports import CoachPayoutSnapshotReader

# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------

_FOUR_DP = Decimal("0.0001")
_ONE = Decimal("1.0")


class CoachUtilizationPoint(BaseModel):
    """Utilization metrics for one coach in one period."""

    model_config = {"frozen": True}

    coach_id: str
    period: str
    hours: Decimal  # total hours from CoachPayoutSnapshot
    payout_minor: int  # total payout in minor currency units
    utilization_rate: Decimal  # hours / max_hours, 4dp, capped at 1.0


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
        snapshot_repo: Port that reads persisted ``CoachPayoutSnapshot``
            records from the data store.
        academy_id: Scopes the query to a single academy.
        max_hours: Soft cap for the utilization rate denominator.  A coach
            with ``hours >= max_hours`` receives a rate of ``1.0``.
            Defaults to 40 (a full-time equivalent month of coaching).
    """

    def __init__(
        self,
        *,
        snapshot_repo: CoachPayoutSnapshotReader,
        academy_id: str,
        max_hours: int = 40,
    ) -> None:
        self._repo = snapshot_repo
        self._academy_id = academy_id
        self._max_hours = Decimal(max_hours)

    async def execute(self, periods: list[str]) -> CoachUtilizationResult:
        """Return utilization data for the requested periods.

        Args:
            periods: List of opaque period strings (e.g. ``["2026-04", "2026-05"]``).
                An empty list returns an empty result with total_payout_minor 0.

        Returns:
            ``CoachUtilizationResult`` with one ``CoachUtilizationPoint`` per
            (coach, period) pair found in the snapshots.  Periods or coaches
            that have no snapshots simply do not appear in the output.
        """
        if not periods:
            return CoachUtilizationResult(
                coaches=[],
                periods=periods,
                total_payout_minor=0,
            )

        snapshots = await self._repo.list_snapshots_for_periods(
            academy_id=self._academy_id,
            periods=periods,
        )

        points: list[CoachUtilizationPoint] = []
        total_payout = 0

        for snap in snapshots:
            if snap.period not in periods:
                continue  # defensive — reader should already filter

            rate = (snap.hours / self._max_hours).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)
            if rate > _ONE:
                rate = _ONE

            points.append(
                CoachUtilizationPoint(
                    coach_id=snap.coach_id,
                    period=snap.period,
                    hours=snap.hours,
                    payout_minor=snap.payout_minor,
                    utilization_rate=rate,
                )
            )
            total_payout += snap.payout_minor

        return CoachUtilizationResult(
            coaches=points,
            periods=periods,
            total_payout_minor=total_payout,
        )
