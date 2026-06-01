"""SessionWriter — atomic capacity reservation via Mongo conditional update.

The atomic guarantee comes from a single update_one with the predicate
``reserved_seats < capacity`` — Mongo serializes concurrent writers, the
loser gets matched_count == 0 and we return False.
"""

from __future__ import annotations

from bson import ObjectId

from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import MongoSessionRepository
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSessionWriter(TenantScopedRepository):
    collection_name = "sessions"

    async def get(self, session_id: str) -> Session | None:
        doc = await self._find_one(_session_filter(session_id))
        return MongoSessionRepository._to_domain(doc) if doc else None

    async def try_reserve_seat(self, session_id: str) -> bool:
        session_filter = _session_filter(session_id)
        result = await self.collection.update_one(
            self._scoped(
                {
                    **session_filter,
                    "status": {"$in": ["scheduled", "active", "open"]},
                    "$expr": {
                        "$lt": [
                            {"$ifNull": ["$reserved_seats", 0]},
                            {"$ifNull": ["$capacity", "$max_students"]},
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
                    **_session_filter(session_id),
                    "$expr": {"$gt": [{"$ifNull": ["$reserved_seats", 0]}, 0]},
                }
            ),
            {"$inc": {"reserved_seats": -1}},
        )

    async def update_status(self, session_id: str, status: str) -> None:
        await self._update_one(_session_filter(session_id), {"$set": {"status": status}})

    async def create(self, session: Session) -> None:
        doc = session.model_dump(mode="python")
        doc["reserved_seats"] = 0
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def update(self, session: Session) -> None:
        doc = session.model_dump(mode="python")
        await self._update_one(
            _session_filter(session.session_id),
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
        )


def _session_filter(session_id: str) -> dict[str, object]:
    if ObjectId.is_valid(session_id):
        return {"$or": [{"session_id": session_id}, {"_id": ObjectId(session_id)}]}
    return {"session_id": session_id}
