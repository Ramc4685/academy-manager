"""Backfill ``users.normalized_email`` so sign-in can look users up exactly.

``LoadAuthClaims`` resolves the account on every authenticated request through
``MongoUserRepository.get_by_email``, which was a case-insensitive ``$regex``
on ``email`` that no index can serve. The repo now does an equality lookup on
``normalized_email`` (``users_normalized_email_unique``, sparse, from 0080) and
falls back to the regex only for rows still missing the field. Newer writers
already set it; this stamps the older rows.

Per row, never one bulk write: two legacy rows that differ only by letter case
would collide on the unique index. The first keeps the value, the other is
skipped and logged so the deploy never fails on dirty data. The skipped row is
then unreachable by email: the exact lookup finds the row that kept the value
first, so the regex fallback never runs for that address. Merge such pairs by
hand from the log. Rows marked ``status: "deleted"`` are
skipped: account erasure unsets the field on purpose. Idempotent.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

version = "0228_users_backfill_normalized_email"

_log = logging.getLogger(__name__)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    users = db["users"]
    cursor = users.find(
        {
            "normalized_email": {"$exists": False},
            "email": {"$type": "string"},
            "status": {"$ne": "deleted"},
        },
        {"_id": 1, "email": 1},
    )
    skipped = 0
    async for doc in cursor:
        normalized = str(doc["email"]).strip().lower()
        if not normalized:
            continue
        try:
            await users.update_one(
                {"_id": doc["_id"], "normalized_email": {"$exists": False}},
                {"$set": {"normalized_email": normalized}},
            )
        except DuplicateKeyError:
            skipped += 1
            _log.warning(
                "migration_0228_case_duplicate_email", extra={"user_doc_id": str(doc["_id"])}
            )
    if skipped:
        _log.warning("migration_0228_skipped_case_duplicates", extra={"count": skipped})
