"""Mongo-backed IdempotencyStore."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

#: A claim older than this belongs to a request that died mid-flight (a crash or
#: a deploy); the next retry takes it over instead of waiting out the 7-day TTL.
CLAIM_STALE_AFTER = timedelta(minutes=5)


class MongoIdempotencyStore:
    """Stores idempotency results in the `idempotency_keys` collection.

    Index + TTL are created by migration `0001_idempotency_keys.py`.

    Note: this store is intentionally *not* tenant-scoped itself. Idempotency
    keys must be globally unique, so callers MUST embed server-derived scope
    (tenant, actor) in the key whenever any key component is client-supplied —
    a raw client value like ``mutation_id`` is attacker-controlled and can be
    replayed across tenants (#544).
    """

    COLLECTION = "idempotency_keys"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[self.COLLECTION]

    async def get(self, key: str) -> dict[str, Any] | None:
        # Return exactly the value that ``put`` stored — NOT the wrapper document.
        # The @idempotent decorator (and its in-memory test fake) treat get/put as
        # symmetric: get(key) yields the value passed to put(key, value). Returning
        # the full {"key", "value", "created_at"} doc here made the decorator
        # deserialize the wrong shape and raise KeyError('_type') on every cache hit.
        doc = await self._collection.find_one({"key": key})
        return None if doc is None else doc.get("value")

    async def put(self, key: str, value: dict[str, Any]) -> None:
        await self._collection.insert_one(
            {
                "key": key,
                "value": value,
                "created_at": datetime.now(UTC),
            }
        )

    async def claim(self, key: str, *, takeover: bool = True) -> datetime | None:
        # Millisecond precision: Mongo stores dates in ms, and the token must
        # match the stored value exactly when it is released.
        now = datetime.now(UTC)
        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
        try:
            await self._collection.insert_one({"key": key, "claimed_at": now, "created_at": now})
            return now
        except DuplicateKeyError:
            if not takeover:
                return None
            # Take over a stale claim atomically: only one retry can match it. A
            # claim written by put() before claims existed has no claimed_at.
            taken = await self._collection.update_one(
                {
                    "key": key,
                    "$or": [
                        {"claimed_at": {"$lt": now - CLAIM_STALE_AFTER}},
                        # Legacy claim shape only, never a stored put() result.
                        {"claimed_at": {"$exists": False}, "value.started_at": {"$exists": True}},
                    ],
                },
                {"$set": {"claimed_at": now, "created_at": now}},
            )
            return now if taken.modified_count == 1 else None

    async def release(self, key: str, token: object) -> None:
        # Only the holder's own claim: a request whose claim was taken over as
        # stale must not free the claim of the request that took it.
        await self._collection.delete_one({"key": key, "claimed_at": token})
