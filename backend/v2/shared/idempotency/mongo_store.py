"""Mongo-backed IdempotencyStore."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


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
