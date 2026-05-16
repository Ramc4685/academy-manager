"""WaitlistRepository — FIFO promotion ordered by joined_at."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoWaitlistRepository(TenantScopedRepository):
    collection_name = "waitlist"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> WaitlistEntry:
        return WaitlistEntry(
            waitlist_id=str(doc["waitlist_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            parent_id=str(doc["parent_id"]),
            joined_at=doc["joined_at"],  # type: ignore[arg-type]
            status=doc.get("status", "waiting"),  # type: ignore[arg-type]
        )

    async def add(self, entry: WaitlistEntry) -> None:
        doc = entry.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        cursor = self._find_many(
            {"session_id": session_id, "status": "waiting"},
            sort=[("joined_at", 1)],
            limit=1,
        )
        async for doc in cursor:
            return self._to_domain(doc)
        return None

    async def update_status(self, waitlist_id: str, status: str) -> None:
        await self._update_one(
            {"waitlist_id": waitlist_id}, {"$set": {"status": status}}
        )
