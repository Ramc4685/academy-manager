"""``ai_call_counters``: the hard AI cap's reservations, tenant-scoped
(migration 0226). One document per ``(academy_id, key)``; ``key`` is
``month:YYYY-MM`` or ``day:YYYY-MM-DD:<feature>``, so a new UTC month or day
starts a new document at zero."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAiCallCounterRepository(TenantScopedRepository):
    collection_name = "ai_call_counters"

    async def reserve(self, key: str, cap: int) -> bool:
        """Take one slot if ``count < cap``, atomically. False at the cap.

        Two steps, so the cap fails closed even without migration 0226's
        unique index: first create the period's document at zero if it is
        missing (``$setOnInsert`` adds no capacity to an existing document),
        then a conditional ``$inc`` that never upserts. A concurrent
        first-of-the-period insert loses on the unique index; that is fine,
        the document exists either way."""
        if cap <= 0:
            return False
        try:
            await self._update_one({"key": key}, {"$setOnInsert": {"count": 0}}, upsert=True)
        except DuplicateKeyError:
            pass
        doc = await self._find_one_and_update(
            {"key": key, "count": {"$lt": cap}}, {"$inc": {"count": 1}}
        )
        return doc is not None

    async def release(self, key: str) -> None:
        """Give back one slot taken by ``reserve``; never below zero."""
        await self._update_one({"key": key, "count": {"$gt": 0}}, {"$inc": {"count": -1}})
