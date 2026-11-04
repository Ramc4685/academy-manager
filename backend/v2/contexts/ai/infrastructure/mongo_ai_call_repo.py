"""``ai_calls`` audit rows, tenant-scoped (migration 0218)."""

from __future__ import annotations

from datetime import datetime

from backend.v2.contexts.ai.domain.models import AiCallRecord
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAiCallRepository(TenantScopedRepository):
    collection_name = "ai_calls"

    async def record(self, call: AiCallRecord) -> None:
        await self._insert_one(call.model_dump(mode="python"))

    async def count_since(self, since: datetime) -> int:
        return await self._count({"created_at": {"$gte": since}})
