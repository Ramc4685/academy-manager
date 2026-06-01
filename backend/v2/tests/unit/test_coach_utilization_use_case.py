"""Unit tests for GetCoachUtilization use case.

All tests use a simple stub ``CoachPayoutSnapshotReader`` — no Mongo
required.

Note: ``CoachPayoutSnapshot`` stores ``payout_minor`` (not ``payout_cents``)
and ``hours`` (Decimal).  The use case derives utilization_rate as
``hours / max_hours`` (default max_hours=40), capped at 1.0, 4dp.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.coach_utilization import (
    CoachUtilizationResult,
    GetCoachUtilization,
)
from backend.v2.contexts.finance.domain.reporting_snapshots import CoachPayoutSnapshot

_NOW = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def _snap(
    coach_id: str,
    period: str,
    hours: str,
    payout_minor: int,
    academy_id: str = "test-academy",
) -> CoachPayoutSnapshot:
    return CoachPayoutSnapshot(
        academy_id=academy_id,
        coach_id=coach_id,
        period=period,
        hours=Decimal(hours),
        payout_minor=payout_minor,
        currency="USD",
        computed_at=_NOW,
    )


class StubSnapshotReader:
    """Stub implementation of CoachPayoutSnapshotReader for unit tests."""

    def __init__(self, snapshots: list[CoachPayoutSnapshot]) -> None:
        self._snapshots = snapshots

    async def list_snapshots_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[CoachPayoutSnapshot]:
        return [s for s in self._snapshots if s.period in periods]


def _use_case(
    snapshots: list[CoachPayoutSnapshot],
    max_hours: int = 40,
) -> GetCoachUtilization:
    return GetCoachUtilization(
        snapshot_repo=StubSnapshotReader(snapshots),
        academy_id="test-academy",
        max_hours=max_hours,
    )


@pytest.mark.asyncio
async def test_aggregates_payout_minor_across_periods():
    """total_payout_minor is the sum of all coach payout_minor across all periods."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-04", hours="20.0", payout_minor=100000),
            _snap("coach-2", "2026-04", hours="10.0", payout_minor=50000),
            _snap("coach-1", "2026-05", hours="30.0", payout_minor=150000),
        ]
    )
    result = await uc.execute(["2026-04", "2026-05"])

    assert result.total_payout_minor == 300000
    assert len(result.coaches) == 3
    assert result.periods == ["2026-04", "2026-05"]


@pytest.mark.asyncio
async def test_utilization_rate_capped_at_one():
    """A coach with hours exceeding max_hours gets utilization_rate == 1.0."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="50.0", payout_minor=200000),
        ],
        max_hours=40,
    )
    result = await uc.execute(["2026-05"])

    assert len(result.coaches) == 1
    point = result.coaches[0]
    assert point.utilization_rate == Decimal("1.0")


@pytest.mark.asyncio
async def test_utilization_rate_calculated_correctly():
    """utilization_rate = hours / max_hours, rounded to 4dp."""
    # 20 hours / 40 max = 0.5000
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="20.0", payout_minor=80000),
        ],
        max_hours=40,
    )
    result = await uc.execute(["2026-05"])

    assert len(result.coaches) == 1
    point = result.coaches[0]
    assert point.coach_id == "coach-1"
    assert point.period == "2026-05"
    assert point.hours == Decimal("20.0")
    assert point.payout_minor == 80000
    assert point.utilization_rate == Decimal("0.5000")


@pytest.mark.asyncio
async def test_empty_periods_returns_empty_coaches():
    """Passing an empty periods list returns a result with no coaches and payout 0."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="20.0", payout_minor=80000),
        ]
    )
    result = await uc.execute([])

    assert result.coaches == []
    assert result.periods == []
    assert result.total_payout_minor == 0
    assert isinstance(result, CoachUtilizationResult)
