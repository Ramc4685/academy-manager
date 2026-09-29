"""Audit rows for uploaded academy media (``academy_media``, tenant-scoped)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAcademyMediaRepository(TenantScopedRepository):
    collection_name = "academy_media"

    async def record(self, doc: dict[str, Any]) -> None:
        await self._insert_one({"_id": new_ulid(), **doc})

    async def count_since(self, since: datetime) -> int:
        return int(
            await self.collection.count_documents(self._scoped({"created_at": {"$gte": since}}))
        )
