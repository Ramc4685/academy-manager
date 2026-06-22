"""Create enrollment billing deferral indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0134"


async def up(db: AsyncIOMotorDatabase) -> None:
    collection = db["enrollment_billing_deferrals"]
    await collection.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("status", 1)],
        name="academy_enrollment_active_deferrals",
    )
    await collection.create_index(
        [("academy_id", 1), ("status", 1), ("billing_period", 1)],
        name="academy_status_billing_period",
    )
    await collection.create_index(
        [("academy_id", 1), ("status", 1), ("resume_on", 1)],
        name="academy_resume_review",
    )
    await collection.create_index(
        [("academy_id", 1), ("source", 1), ("source_id", 1), ("billing_period", 1)],
        name="academy_source_period",
    )
