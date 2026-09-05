"""Create the outbox + dead-letter + handler-runs + audit indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0002"


async def up(db: AsyncIOMotorDatabase) -> None:
    outbox = db["outbox_events"]
    await outbox.create_index([("processed", 1), ("created_at", 1)], name="dispatcher_poll")
    await outbox.create_index("event_id", unique=True, name="event_id_unique")

    runs = db["event_handler_runs"]
    await runs.create_index(
        [("event_id", 1), ("handler_name", 1)],
        unique=True,
        name="event_handler_unique",
    )

    dead = db["dead_letter_events"]
    await dead.create_index([("created_at", 1)], name="created_at")

    audit = db["event_audit"]
    # 90-day TTL on completed_at (extended to 400 days by migration 0166).
    await audit.create_index(
        "completed_at", expireAfterSeconds=90 * 24 * 60 * 60, name="completed_at_ttl"
    )
    await audit.create_index(
        [("academy_id", 1), ("name", 1), ("completed_at", 1)],
        name="per_tenant_event_timeline",
    )
