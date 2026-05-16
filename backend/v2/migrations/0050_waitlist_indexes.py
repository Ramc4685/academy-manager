"""Waitlist indexes — FIFO promotion."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0050"


async def up(db: AsyncIOMotorDatabase) -> None:
    wl = db["waitlist"]
    await wl.create_index("waitlist_id", unique=True, name="waitlist_id_unique")
    await wl.create_index(
        [("academy_id", 1), ("session_id", 1), ("joined_at", 1)],
        name="fifo_promotion",
    )
    await wl.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="parent_view",
    )
