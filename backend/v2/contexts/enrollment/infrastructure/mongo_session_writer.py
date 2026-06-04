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

_DOW_INDEX = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalize_days(days: object) -> tuple[str, ...]:
    reverse_dow = {
        0: "Mon",
        1: "Tue",
        2: "Wed",
        3: "Thu",
        4: "Fri",
        5: "Sat",
        6: "Sun",
    }
    values = list(days or []) if isinstance(days, list) else []
    return tuple(reverse_dow[_DOW_INDEX[day]] for day in values if day in _DOW_INDEX)


def _series_signature(
    *,
    title: object,
    location: object,
    coach_id: object,
    days_of_week: object,
    start_time: object,
    end_time: object,
    timezone: object,
) -> tuple[object, ...]:
    return (
        _normalize_text(location),
        str(coach_id or ""),
        _normalize_days(days_of_week),
        str(start_time or ""),
        str(end_time or ""),
        str(timezone or "America/Chicago"),
    )


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

    async def find_duplicate_recurring_series(
        self,
        *,
        title: str,
        location: str,
        coach_id: str,
        days_of_week: list[str],
        start_time: str,
        end_time: str,
        timezone: str,
        exclude_session_id: str | None = None,
    ) -> Session | None:
        target = _series_signature(
            title=title,
            location=location,
            coach_id=coach_id,
            days_of_week=days_of_week,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
        )
        cursor = self._find_many(
            {
                "coach_id": coach_id,
                "status": {"$in": ["scheduled", "active", "open"]},
                "days_of_week": {"$exists": True, "$ne": []},
                "start_time": start_time,
                "end_time": end_time,
            },
            sort=[("start_at", 1)],
        )
        async for doc in cursor:
            session_id = str(doc.get("session_id") or doc.get("_id"))
            if exclude_session_id and session_id == exclude_session_id:
                continue
            signature = _series_signature(
                title=doc.get("title") or doc.get("name") or "",
                location=doc.get("location") or "",
                coach_id=doc.get("coach_id") or "",
                days_of_week=doc.get("days_of_week") or [],
                start_time=doc.get("start_time") or "",
                end_time=doc.get("end_time") or "",
                timezone=doc.get("timezone") or "America/Chicago",
            )
            if signature == target:
                return MongoSessionRepository._to_domain(doc)
        return None


def _session_filter(session_id: str) -> dict[str, object]:
    if ObjectId.is_valid(session_id):
        return {"$or": [{"session_id": session_id}, {"_id": ObjectId(session_id)}]}
    return {"session_id": session_id}
