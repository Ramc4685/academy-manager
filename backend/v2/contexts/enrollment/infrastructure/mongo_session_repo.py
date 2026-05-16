"""Mongo SessionQuery."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import TenantScopedRepository


def _day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(on_date, time.max, tzinfo=timezone.utc)
    return start, end


class MongoSessionRepository(TenantScopedRepository):
    collection_name = "sessions"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Session:
        return Session(
            session_id=str(doc["session_id"]),
            academy_id=str(doc["academy_id"]),
            coach_id=str(doc["coach_id"]),
            title=str(doc["title"]),
            location=str(doc["location"]),
            start_at=doc["start_at"],  # type: ignore[arg-type]
            end_at=doc["end_at"],  # type: ignore[arg-type]
            capacity=int(doc["capacity"]),  # type: ignore[arg-type]
            status=doc.get("status", "scheduled"),  # type: ignore[arg-type]
        )

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        start, end = _day_bounds_utc(on_date)
        cursor = self._find_many(
            {"coach_id": coach_id, "start_at": {"$gte": start, "$lte": end}},
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def get(self, session_id: str) -> Session | None:
        doc = await self._find_one({"session_id": session_id})
        return self._to_domain(doc) if doc else None
