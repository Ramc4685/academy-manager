"""Mongo SessionQuery."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ParentAvailableSession,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import TenantScopedRepository


def _day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(on_date, time.max, tzinfo=timezone.utc)
    return start, end


class MongoSessionRepository(TenantScopedRepository):
    collection_name = "sessions"

    def __init__(self, db: Any, *, default_amount_cents: int = 15000) -> None:
        super().__init__(db)
        self._default_amount_cents = default_amount_cents

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Session:
        # Normalise legacy schema (name/max_students) to v2 schema (title/capacity).
        return Session(
            session_id=str(doc.get("session_id") or doc.get("_id")),
            academy_id=str(doc.get("academy_id") or "default-academy"),
            coach_id=str(doc.get("coach_id") or ""),
            title=str(doc.get("title") or doc.get("name") or "Session"),
            location=str(doc.get("location") or ""),
            start_at=doc["start_at"],  # type: ignore[arg-type]
            end_at=doc["end_at"],  # type: ignore[arg-type]
            capacity=int(doc.get("capacity") or doc.get("max_students") or 15),  # type: ignore[arg-type]
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

    async def available_for_parent_catalog(self) -> list[ParentAvailableSession]:
        now = datetime.now(timezone.utc)
        cursor = self._find_many(
            {
                "status": {"$nin": ["cancelled", "completed"]},
                "start_at": {"$gte": now},
            },
            sort=[("start_at", 1)],
            limit=100,
        )
        rows: list[ParentAvailableSession] = []
        async for doc in cursor:
            capacity = int(doc.get("capacity") or doc.get("max_students") or 1)
            session_id = str(doc["session_id"])
            enrolled_count = int(
                await self._db["enrollments"].count_documents(
                    self._scoped({"session_id": session_id, "status": "active"})
                )
            )
            reserved_seats = int(doc.get("reserved_seats") or enrolled_count)
            occupied = max(enrolled_count, reserved_seats)
            available_seats = max(capacity - occupied, 0)
            if available_seats <= 0:
                continue
            rows.append(
                ParentAvailableSession(
                    session_id=session_id,
                    title=str(doc.get("title") or doc.get("name") or "Academy session"),
                    location=str(doc.get("location") or ""),
                    start_at=doc["start_at"],  # type: ignore[arg-type]
                    end_at=doc["end_at"],  # type: ignore[arg-type]
                    capacity=capacity,
                    enrolled_count=enrolled_count,
                    available_seats=available_seats,
                    amount_cents=_amount_cents(doc, self._default_amount_cents),
                )
            )
        return rows


def _amount_cents(doc: dict[str, object], default_amount_cents: int) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return int(round(float(doc["monthly_price"]) * 100))  # type: ignore[arg-type]
    return default_amount_cents
