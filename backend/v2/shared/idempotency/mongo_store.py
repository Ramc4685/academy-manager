"""Mongo-backed IdempotencyStore."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase


class MongoIdempotencyStore:
    """Stores idempotency results in the `idempotency_keys` collection.

    Index + TTL are created by migration `0001_idempotency_keys.py`.

    Note: this is intentionally *not* tenant-scoped. Idempotency keys must be
    globally unique (callers prefix them with the tenant if cross-tenant
    collisions are possible — they are not, for `mutation_id` ULIDs).
    """

    COLLECTION = "idempotency_keys"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[self.COLLECTION]

    async def get(self, key: str) -> dict[str, Any] | None:
        return await self._collection.find_one({"key": key})

    async def put(self, key: str, value: dict[str, Any]) -> None:
        await self._collection.insert_one(
            {
                "key": key,
                "value": value,
                "created_at": datetime.now(UTC),
            }
        )
