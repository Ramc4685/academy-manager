"""``ai_call_counters``: the hard AI cap's reservations, tenant-scoped
(migration 0226). One document per ``(academy_id, key)``; ``key`` is
``month:YYYY-MM`` or ``day:YYYY-MM-DD:<feature>``, so a new UTC month or day
starts a new document at zero."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoAiCallCounterRepository(TenantScopedRepository):
    collection_name = "ai_call_counters"

    async def reserve(self, key: str, cap: int) -> bool:
        """Take one slot if ``count < cap``, atomically. False at the cap.

        Two steps, so the cap fails closed even without migration 0226's
        index: first create the period's document at zero if it is missing
        (``$setOnInsert`` adds no capacity to an existing document), then a
        conditional ``$inc`` that never upserts. The document's ``_id`` is
        ``<academy_id>:<key>``, so the always-unique ``_id`` index keeps racing
        first-of-the-period inserts to one document; the loser's duplicate-key
        error is expected and ignored."""
        if cap <= 0:
            return False
        doc_id = _counter_id(key)
        try:
            await self._update_one(
                {"_id": doc_id, "key": key}, {"$setOnInsert": {"count": 0}}, upsert=True
            )
        except DuplicateKeyError:
            pass
        doc = await self._find_one_and_update(
            {"_id": doc_id, "count": {"$lt": cap}}, {"$inc": {"count": 1}}
        )
        return doc is not None

    async def release(self, key: str) -> None:
        """Give back one slot taken by ``reserve``; never below zero."""
        await self._update_one(
            {"_id": _counter_id(key), "count": {"$gt": 0}}, {"$inc": {"count": -1}}
        )


def _counter_id(key: str) -> str:
    return f"{current_academy_id()}:{key}"
