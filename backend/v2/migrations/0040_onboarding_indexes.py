"""Onboarding indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0040"


async def up(db: AsyncIOMotorDatabase) -> None:
    apps = db["onboarding_applications"]
    await apps.create_index("application_id", unique=True, name="application_id_unique")
    await apps.create_index(
        [("academy_id", 1), ("parent_user_id", 1), ("created_at", -1)],
        name="parent_recent",
    )
    await apps.create_index(
        [("academy_id", 1), ("status", 1)],
        name="status_filter",
    )

    waivers = db["waivers"]
    await waivers.create_index(
        [("academy_id", 1), ("version", 1)],
        unique=True,
        name="academy_version_unique",
    )
    await waivers.create_index(
        [("academy_id", 1), ("effective_from", -1)],
        name="latest_active",
    )
