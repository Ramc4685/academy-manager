"""Backfill ``users.last_login_at`` from the sign-in audit trail.

The parent daily digest treats a parent with no ``last_login_at`` as "never
signed in" and mails them a one-time auto-login link. Nothing wrote the field
until the login recorder started stamping it, so every parent looked
never-activated. Sign-ins have been audited since #468 as ``audit_logs`` rows
with ``action: "user_logged_in"`` and ``actor_id`` = the users row's id; this
copies the latest one onto each users row that has no ``last_login_at`` yet.

Lookups go field by field (``user_id``, then ``auth_uid``, then ``_id``), never
an ``$or`` across them (#894). Idempotent: rows already stamped are untouched.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0229_users_backfill_last_login_at"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    users = db["users"]
    pipeline: list[dict[str, Any]] = [
        {"$match": {"action": "user_logged_in", "actor_id": {"$type": "string"}}},
        {"$group": {"_id": "$actor_id", "last": {"$max": "$created_at"}}},
    ]
    async for row in db["audit_logs"].aggregate(pipeline):
        actor, last = row["_id"], row["last"]
        if not actor or last is None:
            continue
        for field in ("user_id", "auth_uid", "_id"):
            result = await users.update_one(
                {field: actor, "last_login_at": {"$exists": False}},
                {"$set": {"last_login_at": last}},
            )
            if result.matched_count:
                break
