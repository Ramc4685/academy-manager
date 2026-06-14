"""Indexes for admin student-progress engagement reports."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0127_student_progress_engagement_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    skill_prog = db["student_skill_progress"]
    await skill_prog.create_index(
        [("academy_id", 1), ("last_updated_at", -1), ("last_updated_by", 1), ("status", 1)],
        name="skill_progress_engagement_window",
    )
