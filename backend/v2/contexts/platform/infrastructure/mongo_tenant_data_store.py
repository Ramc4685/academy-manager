"""Mongo reader behind tenant export and purge dry-run (roadmap L9d).

Read-only. Every query filters on ``academy_id``; nothing here writes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class MongoTenantDataStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def collection_names(self) -> list[str]:
        # Real collections only: a view would re-export rows it projects.
        names = await self._db.list_collection_names(filter={"type": "collection"})
        return [str(name) for name in names]

    async def count(self, collection: str, academy_id: str) -> int:
        return int(await self._db[collection].count_documents({"academy_id": academy_id}))

    async def documents(self, collection: str, academy_id: str) -> AsyncIterator[dict[str, Any]]:
        cursor = self._db[collection].find({"academy_id": academy_id}).sort("_id", 1)
        async for doc in cursor:
            yield doc
