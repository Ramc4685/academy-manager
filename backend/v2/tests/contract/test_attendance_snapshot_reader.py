"""Contract tests for MongoAttendanceSnapshotReader.

Uses mongomock-motor (via the ``db`` fixture from contract/conftest.py)
to exercise the filter logic without a real Mongo instance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.finance.infrastructure.mongo_attendance_snapshot_reader import (
    MongoAttendanceSnapshotReader,
)

_NOW = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)


def _doc(
    session_id: str,
    academy_id: str,
    period: str,
    scheduled: int = 10,
    completed: int = 8,
    no_show: int = 2,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "academy_id": academy_id,
        "period": period,
        "scheduled_count": scheduled,
        "completed_count": completed,
        "no_show_count": no_show,
        "computed_at": _NOW,
    }


@pytest.mark.asyncio
async def test_returns_snapshots_for_requested_periods(db):
    """Snapshots in requested periods are returned; others are excluded."""
    col = db["session_attendance_snapshots"]
    await col.insert_many(
        [
            _doc("sess-1", "acad-1", "2026-04", scheduled=10, completed=8, no_show=2),
            _doc("sess-2", "acad-1", "2026-05", scheduled=12, completed=10, no_show=2),
            _doc(
                "sess-3", "acad-1", "2026-06", scheduled=8, completed=5, no_show=3
            ),  # not requested
        ]
    )
    reader = MongoAttendanceSnapshotReader(db)
    snapshots = await reader.list_snapshots_for_periods(
        academy_id="acad-1", periods=["2026-04", "2026-05"]
    )

    assert len(snapshots) == 2
    periods_returned = {s.period for s in snapshots}
    assert periods_returned == {"2026-04", "2026-05"}


@pytest.mark.asyncio
async def test_filters_by_academy_id(db):
    """Snapshots belonging to a different academy must not be returned."""
    col = db["session_attendance_snapshots"]
    await col.insert_many(
        [
            _doc("sess-A1", "acad-A", "2026-05", scheduled=10, completed=9, no_show=1),
            _doc("sess-A2", "acad-A", "2026-05", scheduled=5, completed=4, no_show=1),
            _doc("sess-B1", "acad-B", "2026-05", scheduled=8, completed=6, no_show=2),
        ]
    )
    reader = MongoAttendanceSnapshotReader(db)

    snaps_a = await reader.list_snapshots_for_periods(academy_id="acad-A", periods=["2026-05"])
    snaps_b = await reader.list_snapshots_for_periods(academy_id="acad-B", periods=["2026-05"])

    assert len(snaps_a) == 2
    assert all(s.academy_id == "acad-A" for s in snaps_a)

    assert len(snaps_b) == 1
    assert snaps_b[0].academy_id == "acad-B"
    assert snaps_b[0].session_id == "sess-B1"


@pytest.mark.asyncio
async def test_returns_empty_for_unknown_period(db):
    """Querying a period that has no snapshots returns an empty list."""
    col = db["session_attendance_snapshots"]
    await col.insert_one(_doc("sess-1", "acad-1", "2026-05"))

    reader = MongoAttendanceSnapshotReader(db)
    snapshots = await reader.list_snapshots_for_periods(academy_id="acad-1", periods=["2099-12"])

    assert snapshots == []


@pytest.mark.asyncio
async def test_returns_empty_list_when_periods_empty(db, acad):
    reader = MongoAttendanceSnapshotReader(db)
    result = await reader.list_snapshots_for_periods(academy_id=acad, periods=[])
    assert result == []
