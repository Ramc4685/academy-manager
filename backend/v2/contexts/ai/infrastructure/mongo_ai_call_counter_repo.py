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

        The ``$lt`` filter makes the ``$inc`` refuse at the cap; ``upsert``
        creates the period's first document. At the cap the filter misses an
        existing document, the upsert tries to insert a second one and the
        unique ``(academy_id, key)`` index refuses it. That same error is what a
        concurrent first-of-the-period upsert gets, so retry once without
        upsert: the document now exists and the ``$lt`` filter decides."""
        if cap <= 0:
            return False
        filter_ = {"key": key, "count": {"$lt": cap}}
        try:
            doc = await self._find_one_and_update(filter_, {"$inc": {"count": 1}}, upsert=True)
        except DuplicateKeyError:
            doc = await self._find_one_and_update(filter_, {"$inc": {"count": 1}})
        return doc is not None

    async def release(self, key: str) -> None:
        """Give back one slot taken by ``reserve``; never below zero."""
        await self._update_one({"key": key, "count": {"$gt": 0}}, {"$inc": {"count": -1}})
