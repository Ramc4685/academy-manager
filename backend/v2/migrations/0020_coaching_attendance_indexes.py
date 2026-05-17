"""Attendance indexes per plan §0.7.

The unique index on (academy_id, session_id, student_id) is the server-side
half of the offline-policy idempotency contract: two devices marking the
same student in the same session race the unique index and the loser
returns ``ConflictAttendanceExists``.
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
