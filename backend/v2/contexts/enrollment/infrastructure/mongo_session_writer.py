"""SessionWriter — atomic capacity reservation via Mongo conditional update.

The atomic guarantee comes from a single update_one with the predicate
``reserved_seats < capacity`` — Mongo serializes concurrent writers, the
loser gets matched_count == 0 and we return False.
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSessionWriter(TenantScopedRepository):
    collection_name = "sessions"

    async def try_reserve_seat(self, session_id: str) -> bool:
        result = await self.collection.update_one(
            self._scoped(
                {
                    "session_id": session_id,
                    "status": "scheduled",
                    "$expr": {
                        "$lt": [
                            {"$ifNull": ["$reserved_seats", 0]},
                            "$capacity",
                        ]
                    },
                }
            ),
            {"$inc": {"reserved_seats": 1}},
        )
        return result.matched_count == 1

    async def release_seat(self, session_id: str) -> None:
        await self.collection.update_one(
            self._scoped(
                {
                    "session_id": session_id,
                    "$expr": {"$gt": [{"$ifNull": ["$reserved_seats", 0]}, 0]},
                }
            ),
            {"$inc": {"reserved_seats": -1}},
        )

    async def update_status(self, session_id: str, status: str) -> None:
        await self._update_one({"session_id": session_id}, {"$set": {"status": status}})

    async def create(self, session: Session) -> None:
        doc = session.model_dump(mode="python")
        doc["reserved_seats"] = 0
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def update(self, session: Session) -> None:
        doc = session.model_dump(mode="python")
        await self._update_one(
            {"session_id": session.session_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
        )
