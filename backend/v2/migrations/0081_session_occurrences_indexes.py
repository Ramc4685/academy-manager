"""Session occurrence indexes and occurrence-keyed attendance uniqueness."""

from __future__ import annotations

from contextlib import suppress

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0081"


async def up(db: AsyncIOMotorDatabase) -> None:
    occurrences = db["session_occurrences"]
    await occurrences.create_index(
        [("academy_id", 1), ("session_id", 1), ("start_at", 1)],
        unique=True,
        name="session_occurrence_unique_start",
    )
    await occurrences.create_index(
        [("academy_id", 1), ("actual_coach_id", 1), ("start_at", 1)],
        name="session_occurrence_actual_coach",
    )
    await occurrences.create_index(
        [("academy_id", 1), ("status", 1), ("start_at", 1)],
        name="session_occurrence_status_calendar",
    )
    await occurrences.create_index(
        "occurrence_id",
        unique=True,
        sparse=True,
        name="session_occurrence_id_unique",
    )

    attendance = db["attendance"]
    with suppress(Exception):
        await attendance.drop_index("attendance_unique")
    await attendance.create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("student_id", 1)],
        unique=True,
        name="attendance_occurrence_unique",
        partialFilterExpression={"occurrence_id": {"$type": "string"}},
    )
