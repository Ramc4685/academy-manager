"""Enrollment lifecycle event indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0090_enrollment_event_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    events = db["enrollment_events"]
    await events.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("occurred_at", 1)],
        name="enrollment_event_timeline",
    )
    await events.create_index(
        [("academy_id", 1), ("waitlist_id", 1), ("occurred_at", 1)],
        name="waitlist_event_timeline",
        sparse=True,
    )
    await events.create_index(
        [("academy_id", 1), ("event_type", 1), ("effective_at", 1)],
        name="enrollment_event_type_effective",
    )
    await events.create_index("event_id", unique=True, name="event_id_unique")
