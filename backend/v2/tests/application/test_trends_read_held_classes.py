"""Attendance trends and coach utilisation read real class dates (S37).

They used to read snapshot collections nothing wrote, so they showed 0 next
to a month close that counted real classes. Both now go through the shared
held-class definition, so "completed" agrees with the reports dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import backend.v2.contexts.billing.infrastructure.admin_reports_read_model as reports_read_model
from backend.v2.contexts.finance.application.use_cases.attendance_trends import (
    GetAttendanceTrends,
)
from backend.v2.contexts.finance.application.use_cases.coach_utilization import (
    GetCoachUtilization,
)
from backend.v2.contexts.finance.infrastructure.mongo_held_class_reader import (
    MongoHeldClassReader,
)
from backend.v2.shared.tenancy.context import tenant_scope


async def _seed(db) -> None:
    await db["academies"].insert_one({"academy_id": "acad", "timezone": "America/Chicago"})
    await db["sessions"].insert_one({"session_id": "sess-1", "academy_id": "acad", "capacity": 12})
    rows = [
        # Four Saturday classes in May (09:00-10:00 Chicago = 14:00-15:00 UTC).
        *[
            {
                "occurrence_id": f"occ-{day}",
                "status": "scheduled",
                "start_at": datetime(2026, 5, day, 14, tzinfo=UTC),
                "end_at": datetime(2026, 5, day, 15, tzinfo=UTC),
                "scheduled_coach_id": "coach-1",
                "assistant_coach_ids": ["coach-2"] if day == 9 else [],
            }
            for day in (2, 9, 16, 23)
        ],
        {
            "occurrence_id": "occ-30",
            "status": "cancelled",
            "start_at": datetime(2026, 5, 30, 14, tzinfo=UTC),
            "end_at": datetime(2026, 5, 30, 15, tzinfo=UTC),
            "scheduled_coach_id": "coach-1",
        },
        # 03:00 UTC on June 1 is still May 31 in Chicago.
        {
            "occurrence_id": "occ-may31-late",
            "status": "scheduled",
            "start_at": datetime(2026, 6, 1, 3, tzinfo=UTC),
            "end_at": datetime(2026, 6, 1, 3, 30, tzinfo=UTC),
            "scheduled_coach_id": "coach-1",
            "actual_coach_id": "coach-sub",
        },
    ]
    await db["session_occurrences"].insert_many(
        [{"academy_id": "acad", "session_id": "sess-1", **row} for row in rows]
    )
    await db["attendance"].insert_many(
        [
            {
                "academy_id": "acad",
                "occurrence_id": "occ-2",
                "status": "present",
                "marked_at": datetime(2026, 5, 2, tzinfo=UTC),
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-2",
                "status": "absent",
                "marked_at": datetime(2026, 5, 2, tzinfo=UTC),
            },
            {
                "academy_id": "acad",
                "occurrence_id": "occ-9",
                "status": "absent",
                "marked_at": datetime(2026, 6, 3, tzinfo=UTC),
            },
        ]
    )
    await db["payout_periods"].insert_one(
        {
            "period_id": "pp-1",
            "academy_id": "acad",
            "coach_id": "coach-1",
            "period_start": datetime(2026, 5, 1, 5, tzinfo=UTC),
            "period_end": datetime(2026, 6, 1, 5, tzinfo=UTC),
            "status": "approved",
            "total_minor": 12_000,
        }
    )


def _db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_attendance_trends_count_held_classes_and_agree_with_the_dashboard() -> None:
    db = _db()
    await _seed(db)

    trends = await GetAttendanceTrends(classes=MongoHeldClassReader(db), academy_id="acad").execute(
        ["2026-05", "2026-06"]
    )
    with tenant_scope("acad"):
        dashboard = await reports_read_model.make_reports_dashboard(db)("2026-05")

    may, june = trends.periods
    assert (may.scheduled_count, may.completed_count, may.no_show_count) == (5, 5, 2)
    assert may.completion_rate == Decimal("1.0000")
    assert may.completed_count == dashboard["sessions"]["completed_count"]
    assert (june.scheduled_count, june.completed_count) == (0, 0)


@pytest.mark.asyncio
async def test_upcoming_classes_are_scheduled_not_completed() -> None:
    db = _db()
    await _seed(db)
    frozen = MongoHeldClassReader(db, clock=lambda: datetime(2026, 5, 10, tzinfo=UTC))

    (may,) = (
        await GetAttendanceTrends(classes=frozen, academy_id="acad").execute(["2026-05"])
    ).periods

    assert (may.scheduled_count, may.completed_count) == (5, 2)


@pytest.mark.asyncio
async def test_coach_utilization_reads_held_hours_for_lead_substitute_and_assistant() -> None:
    db = _db()
    await _seed(db)

    result = await GetCoachUtilization(classes=MongoHeldClassReader(db), academy_id="acad").execute(
        ["2026-05"]
    )

    by_coach = {point.coach_id: point for point in result.coaches}
    assert by_coach["coach-1"].hours == Decimal("4.0000")
    assert by_coach["coach-1"].payout_minor == 12_000
    assert by_coach["coach-2"].hours == Decimal("1.0000")
    assert by_coach["coach-sub"].hours == Decimal("0.5000")
    assert result.total_payout_minor == 12_000


@pytest.mark.asyncio
async def test_held_class_reader_is_tenant_scoped() -> None:
    db = _db()
    await _seed(db)

    trends = await GetAttendanceTrends(
        classes=MongoHeldClassReader(db), academy_id="other"
    ).execute(["2026-05"])

    assert trends.periods[0].scheduled_count == 0
