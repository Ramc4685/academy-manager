"""WaitlistRepository — FIFO promotion ordered by joined_at."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc


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
            joined_at=doc["joined_at"],
            status=doc.get("status", "waiting"),
            # Mongo hands back naive UTC (#706): compare a deadline with an
            # aware `now` without this and the confirm route 500s.
            offer_expires_at=(
                ensure_utc(cast("datetime", raw_expires))
                if (raw_expires := doc.get("offer_expires_at")) is not None
                else None
            ),
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
        await self._update_one({"waitlist_id": waitlist_id}, {"$set": {"status": status}})

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None:
        doc = await self._find_one(
            {"session_id": session_id, "student_id": student_id, "status": "waiting"}
        )
        return self._to_domain(doc) if doc else None

    async def remove_waiting_for_session_student(self, session_id: str, student_id: str) -> None:
        await self.collection.update_many(
            self._scoped({"session_id": session_id, "student_id": student_id, "status": "waiting"}),
            {"$set": {"status": "removed"}},
        )

    # --- Offer window (issue #828) --------------------------------------

    async def get(self, waitlist_id: str) -> WaitlistEntry | None:
        doc = await self._find_one({"waitlist_id": waitlist_id})
        return self._to_domain(doc) if doc else None

    async def mark_offered(self, waitlist_id: str, *, offer_expires_at: datetime) -> None:
        await self._update_one(
            {"waitlist_id": waitlist_id},
            {"$set": {"status": "offered", "offer_expires_at": offer_expires_at}},
        )

    async def find_expired_offers(self, *, before: datetime) -> list[WaitlistEntry]:
        cursor = self._find_many(
            {"status": "offered", "offer_expires_at": {"$lte": before}},
            sort=[("offer_expires_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
