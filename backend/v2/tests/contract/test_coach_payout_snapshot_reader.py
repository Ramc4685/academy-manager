"""Contract tests for MongoCoachPayoutSnapshotReader.

Uses mongomock-motor (via the ``db`` fixture from contract/conftest.py)
to exercise the filter logic without a real Mongo instance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.infrastructure.mongo_coach_payout_snapshot_reader import (
    MongoCoachPayoutSnapshotReader,
)

_NOW = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def _doc(
    coach_id: str,
    academy_id: str,
    period: str,
    hours: str = "10.0",
    payout_minor: int = 50000,
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "coach_id": coach_id,
        "academy_id": academy_id,
        "period": period,
        "hours": hours,
        "payout_minor": payout_minor,
        "currency": currency,
        "computed_at": _NOW,
    }


@pytest.mark.asyncio
async def test_returns_snapshots_for_requested_periods(db):
    """Snapshots in requested periods are returned; others are excluded."""
    col = db["coach_payout_snapshots"]
    await col.insert_many(
        [
            _doc("coach-1", "acad-1", "2026-04", hours="8.0", payout_minor=40000),
            _doc("coach-2", "acad-1", "2026-05", hours="12.0", payout_minor=60000),
            _doc("coach-3", "acad-1", "2026-06", hours="10.0", payout_minor=50000),  # not requested
        ]
    )
    reader = MongoCoachPayoutSnapshotReader(db)
    snapshots = await reader.list_snapshots_for_periods(
        academy_id="acad-1", periods=["2026-04", "2026-05"]
    )

    assert len(snapshots) == 2
    periods_returned = {s.period for s in snapshots}
    assert periods_returned == {"2026-04", "2026-05"}
    assert all(s.academy_id == "acad-1" for s in snapshots)


@pytest.mark.asyncio
async def test_filters_by_academy_id(db):
    """Snapshots belonging to a different academy must not be returned."""
    col = db["coach_payout_snapshots"]
    await col.insert_many(
        [
            _doc("coach-A1", "acad-A", "2026-05", hours="20.0", payout_minor=100000),
            _doc("coach-A2", "acad-A", "2026-05", hours="15.0", payout_minor=75000),
            _doc("coach-B1", "acad-B", "2026-05", hours="10.0", payout_minor=50000),
        ]
    )
    reader = MongoCoachPayoutSnapshotReader(db)

    snaps_a = await reader.list_snapshots_for_periods(academy_id="acad-A", periods=["2026-05"])
    snaps_b = await reader.list_snapshots_for_periods(academy_id="acad-B", periods=["2026-05"])

    assert len(snaps_a) == 2
    assert all(s.academy_id == "acad-A" for s in snaps_a)

    assert len(snaps_b) == 1
    assert snaps_b[0].academy_id == "acad-B"
    assert snaps_b[0].coach_id == "coach-B1"
    assert snaps_b[0].hours == Decimal("10.0")


@pytest.mark.asyncio
async def test_returns_empty_for_unknown_period(db):
    """Querying a period that has no snapshots returns an empty list."""
    col = db["coach_payout_snapshots"]
    await col.insert_one(_doc("coach-1", "acad-1", "2026-05"))

    reader = MongoCoachPayoutSnapshotReader(db)
    snapshots = await reader.list_snapshots_for_periods(academy_id="acad-1", periods=["2099-12"])

    assert snapshots == []


@pytest.mark.asyncio
async def test_returns_empty_list_when_periods_empty(db, acad):
    reader = MongoCoachPayoutSnapshotReader(db)
    result = await reader.list_snapshots_for_periods(academy_id=acad, periods=[])
    assert result == []
