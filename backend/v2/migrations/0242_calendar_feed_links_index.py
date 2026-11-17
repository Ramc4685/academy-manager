"""One calendar-feed link version per parent per academy.

``calendar_feed_links_parent_uq``: unique ``(academy_id, parent_id)``. The
"Reset link" ``$inc`` upserts on exactly this key, so two concurrent first
resets cannot create two rows (the loser retries as an update), and the index
serves the per-request version lookup. Partial on ``{parent_id: {"$gt": ""}}``
(not ``$type``, see 0188). New, empty collection: no backfill.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0242_calendar_feed_links_index"

INDEX = "calendar_feed_links_parent_uq"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["calendar_feed_links"].create_index(
        [("academy_id", 1), ("parent_id", 1)],
        unique=True,
        partialFilterExpression={"parent_id": {"$gt": ""}},
        name=INDEX,
    )
