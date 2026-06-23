"""Legacy attendance indexes per plan §0.7.

Occurrence-keyed attendance uniqueness is created by migration 0081. This
legacy session/student index is scoped away from occurrence rows so full local
replays can run after occurrence-based seed data exists.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0020"


async def up(db: AsyncIOMotorDatabase) -> None:
    attendance = db["attendance"]
    await attendance.create_index(
        [("academy_id", 1), ("session_id", 1), ("student_id", 1)],
        unique=True,
        name="attendance_unique",
        partialFilterExpression={"legacy_session_attendance_unique": True},
    )
    await attendance.create_index(
        [("academy_id", 1), ("marked_by", 1), ("marked_at", 1)],
        name="coach_history",
    )
    await attendance.update_many({"attendance_id": None}, {"$unset": {"attendance_id": ""}})
    await attendance.create_index(
        "attendance_id",
        unique=True,
        name="attendance_id_unique",
        sparse=True,
    )
