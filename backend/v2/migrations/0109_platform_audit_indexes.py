"""Platform audit indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0109_platform_audit_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    events = db["platform_audit_events"]
    await events.create_index("audit_event_id", unique=True, name="audit_event_id_unique")
    await events.create_index(
        [("created_at", -1), ("audit_event_id", -1)],
        name="platform_audit_created_at",
    )
    await events.create_index(
        [("academy_id", 1), ("created_at", -1), ("audit_event_id", -1)],
        name="platform_audit_tenant_timeline",
    )
    await events.create_index(
        [("action", 1), ("created_at", -1)],
        name="platform_audit_action_timeline",
    )
    await events.create_index(
        [("entity_type", 1), ("entity_id", 1), ("created_at", -1)],
        name="platform_audit_entity_timeline",
    )
    await events.create_index(
        "request_id",
        name="platform_audit_request_id",
        sparse=True,
    )
