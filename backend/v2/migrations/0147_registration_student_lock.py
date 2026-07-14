"""Prevent concurrent registration approvals from enrolling one child twice."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0147_registration_student_lock"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db["enrollments"].create_index(
        [("academy_id", 1), ("registration_student_lock", 1)],
        name="uq_registration_active_student_lock",
        unique=True,
        partialFilterExpression={
            "registration_student_lock": {"$type": "string"},
            "status": {"$in": ["active", "paused"]},
        },
    )
