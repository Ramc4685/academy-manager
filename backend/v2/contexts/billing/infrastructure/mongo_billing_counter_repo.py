"""Atomic per-academy counters (e.g. invoice numbering).

Race-safe: uses Mongo's ``find_one_and_update`` with ``$inc`` so concurrent
callers each get a unique, monotonically increasing value.
"""

from __future__ import annotations

from pymongo import ReturnDocument

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoBillingCounterRepository(TenantScopedRepository):
    collection_name = "billing_counters"

    async def next_value(self, *, scope: str) -> int:
        doc = await self.collection.find_one_and_update(
            self._scoped({"scope": scope}),
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["seq"])
