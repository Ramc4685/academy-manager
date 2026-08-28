"""Backfill ``attempt_count`` on existing digest-send rows (issue #435).

The retry re-claim matches ``{"status": "failed", "attempt_count": {"$lt": N}}``.
A missing field does not satisfy ``$lt``, so without this backfill every row
written before #435 would stay permanently unretryable — the exact bug the
change fixes, silently preserved for pre-existing rows.

Idempotent: only documents lacking the field are touched, so a re-run is a
no-op and a row that has already retried keeps its real count.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0153_digest_send_attempt_count"

COLLECTIONS = ("coach_digest_sends", "parent_digest_sends")


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for name in COLLECTIONS:
        await db[name].update_many(
            {"attempt_count": {"$exists": False}},
            {"$set": {"attempt_count": 1}},
        )
