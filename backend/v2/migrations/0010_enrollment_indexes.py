"""Enrollment context indexes — sessions, enrollments, students.

Per docs/data-ownership.md and plan §0.7. Every index leads with
``academy_id`` for tenant filtering (ADR-0006).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0010"


async def _unique_v2_id(collection, field: str, name: str) -> None:
    await collection.update_many({field: None}, {"$unset": {field: ""}})
    await collection.create_index(
        field,
        unique=True,
        name=name,
        sparse=True,
    )


async def up(db: AsyncIOMotorDatabase) -> None:
    sessions = db["sessions"]
    await sessions.create_index(
        [("academy_id", 1), ("coach_id", 1), ("start_at", 1)],
        name="coach_today",
    )
    await sessions.create_index(
        [("academy_id", 1), ("start_at", 1)],
        name="academy_calendar",
    )
    await _unique_v2_id(sessions, "session_id", "session_id_unique")

    enrollments = db["enrollments"]
    await enrollments.create_index(
        [("academy_id", 1), ("session_id", 1)],
        name="roster_by_session",
    )
    await enrollments.create_index(
        [("academy_id", 1), ("student_id", 1)],
        name="enrollments_for_student",
    )
    await enrollments.create_index(
        [("academy_id", 1), ("status", 1), ("session_id", 1)],
        name="capacity_check",
    )
    await _unique_v2_id(enrollments, "enrollment_id", "enrollment_id_unique")

    students = db["students"]
    await students.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="parent_children",
    )
    await _unique_v2_id(students, "student_id", "student_id_unique")
