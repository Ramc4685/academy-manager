"""Parent self-service indexes.

Five new tenant-scoped collections backing the parent self-service feature:
- ``parent_self_service_policies``: one document per academy.
- ``absence_notices``: parent-submitted absence notices for occurrences.
- ``makeup_requests``: parent-submitted makeup requests for missed occurrences.
- ``trial_requests``: parent-submitted trial class requests.
- ``occurrence_roster_entries``: one-time roster entries written on
  makeup/trial approval. The unique index here is LOAD-BEARING: it backs the
  approve-path CAS fix's over-fill mitigation (a double roster write for the
  same student+occurrence must be impossible at the DB level).

``create_index`` is idempotent, so no existence checks are needed.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0145_parent_self_service"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db["parent_self_service_policies"].create_index([("academy_id", 1)], unique=True)

    await db["absence_notices"].create_index([("academy_id", 1), ("occurrence_id", 1)])
    await db["absence_notices"].create_index(
        [("academy_id", 1), ("submitted_by", 1), ("submitted_at", -1)]
    )
    await db["absence_notices"].create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("student_id", 1)], unique=True
    )

    await db["makeup_requests"].create_index([("academy_id", 1), ("status", 1)])
    await db["makeup_requests"].create_index(
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)]
    )
    await db["makeup_requests"].create_index([("academy_id", 1), ("expires_at", 1)])

    await db["trial_requests"].create_index([("academy_id", 1), ("status", 1)])
    await db["trial_requests"].create_index(
        [("academy_id", 1), ("parent_user_id", 1), ("created_at", -1)]
    )

    await db["occurrence_roster_entries"].create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("student_id", 1)], unique=True
    )
    await db["occurrence_roster_entries"].create_index([("academy_id", 1), ("occurrence_id", 1)])
