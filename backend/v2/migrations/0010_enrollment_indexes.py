"""Enrollment context indexes — sessions, enrollments, students.

Per docs/data-ownership.md and plan §0.7. Every index leads with
``academy_id`` for tenant filtering (ADR-0006).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0010"


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
    await sessions.create_index("session_id", unique=True, name="session_id_unique")

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
    await enrollments.create_index("enrollment_id", unique=True, name="enrollment_id_unique")

    students = db["students"]
    await students.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="parent_children",
    )
    await students.create_index("student_id", unique=True, name="student_id_unique")
