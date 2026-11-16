"""One audit row per ``audit_id`` per academy.

Audit writers that must not double a row on retry (the certificate revoke,
the pathway placement) upsert on a deterministic ``audit_id``. Without a unique
index two concurrent upserts can both insert. Every other writer mints a ULID,
so existing rows should already be unique; the migration checks first and, if
not, raises naming the duplicates instead of failing on an opaque
DuplicateKeyError. The partial filter uses ``$gt: ""``, never ``$type``: the
planner ignores ``$type`` partial indexes for equality lookups.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING

version = "0240_audit_logs_audit_id_unique"

COLLECTION = "audit_logs"
INDEX_NAME = "academy_audit_id_unique"
_PARTIAL = {"audit_id": {"$gt": ""}}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    duplicates = await (
        db[COLLECTION]
        .aggregate(
            [
                {"$match": _PARTIAL},
                {
                    "$group": {
                        "_id": {"academy_id": "$academy_id", "audit_id": "$audit_id"},
                        "count": {"$sum": 1},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
                {"$limit": 20},
            ]
        )
        .to_list(None)
    )
    if duplicates:
        named = ", ".join(
            f"{d['_id'].get('academy_id')}/{d['_id']['audit_id']} x{d['count']}" for d in duplicates
        )
        raise RuntimeError(
            f"{COLLECTION} has duplicate (academy_id, audit_id) rows: {named}. "
            "Keep the earliest row of each and delete the rest, then re-run this migration."
        )
    await db[COLLECTION].create_index(
        [("academy_id", ASCENDING), ("audit_id", ASCENDING)],
        unique=True,
        name=INDEX_NAME,
        partialFilterExpression=_PARTIAL,
    )
