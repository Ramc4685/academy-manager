"""Create scheduled enrollment action indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0113"


async def up(db: AsyncIOMotorDatabase) -> None:
    collection = db["scheduled_enrollment_actions"]
    await collection.create_index(
        [("academy_id", 1), ("status", 1), ("run_at", 1)],
        name="due_scheduled_enrollment_actions",
    )
    await collection.create_index(
        [("academy_id", 1), ("pause_request_id", 1), ("action_type", 1)],
        unique=True,
        name="unique_pause_action",
    )
