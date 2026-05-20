"""Admin student directory read indexes.

Supports the Rich Students BFF aggregation: attendance rate over recent marks
and last-seen lookups by academy/student/date.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0070"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db["attendance"].create_index(
        [("academy_id", 1), ("student_id", 1), ("marked_at", -1)],
        name="admin_student_attendance_lookup",
    )
