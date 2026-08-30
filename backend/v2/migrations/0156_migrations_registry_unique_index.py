"""Unique index on the migrations registry itself (issue #507).

Before the boot-time distributed lock, two machines booting concurrently
could both run the same pending migration and both ``insert_one`` its
registry row, leaving duplicates in ``v2_migrations``. The runner now takes
a Mongo lease and records versions via upsert, and this migration adds the
matching defense-in-depth: dedupe any historical duplicate rows (keeping the
earliest ``applied_at``), then enforce uniqueness on ``version`` so a
duplicate registry row can never exist again.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0156_migrations_registry_unique_index"

_REGISTRY = "v2_migrations"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # Dedupe first so the unique index build cannot fail on historical
    # double-applied rows. Keep the earliest applied_at per version.
    seen: dict[str, object] = {}
    duplicate_ids: list[object] = []
    async for doc in db[_REGISTRY].find({}).sort([("version", 1), ("applied_at", 1)]):
        v = doc.get("version")
        if v in seen:
            duplicate_ids.append(doc["_id"])
        else:
            seen[v] = doc["_id"]
    if duplicate_ids:
        await db[_REGISTRY].delete_many({"_id": {"$in": duplicate_ids}})

    await db[_REGISTRY].create_index(
        [("version", 1)],
        unique=True,
        name="v2_migrations_version_unique",
    )
