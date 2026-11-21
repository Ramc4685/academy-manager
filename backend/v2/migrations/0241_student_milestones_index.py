"""One milestone record per student per milestone (L5B PR2).

``student_milestones_one_per_key_uq``: unique ``(academy_id, student_id,
milestone_key)``, partial on ``{milestone_key: {"$gt": ""}}`` (not ``$type``:
the planner ignores ``$type`` partials for equality lookups, see 0188). The
recorder upserts on exactly this key, so the index both makes a repeat a
no-op and serves the lookup. The collection is new and empty: no backfill.

Re-running is a no-op.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0241_student_milestones_index"

INDEX = "student_milestones_one_per_key_uq"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["student_milestones"].create_index(
        [("academy_id", 1), ("student_id", 1), ("milestone_key", 1)],
        unique=True,
        partialFilterExpression={"milestone_key": {"$gt": ""}},
        name=INDEX,
    )
