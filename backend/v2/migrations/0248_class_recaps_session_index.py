"""Class recaps by batch, newest first (append-only, no backfill).

* ``class_recaps_session_idx``: ``(academy_id, session_id, class_starts_at
  desc)``, so Coach Today's teaching plan reads a batch's recent recaps (what
  each level group actually worked on) without scanning the collection.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0248_class_recaps_session_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["class_recaps"].create_index(
        [("academy_id", 1), ("session_id", 1), ("class_starts_at", -1)],
        name="class_recaps_session_idx",
    )
