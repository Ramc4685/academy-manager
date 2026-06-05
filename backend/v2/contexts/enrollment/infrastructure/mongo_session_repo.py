"""Mongo SessionQuery."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ParentAvailableSession,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import TenantScopedRepository


def _day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on_date, time.min, tzinfo=UTC)
    end = datetime.combine(on_date, time.max, tzinfo=UTC)
    return start, end


def session_start_sort_key(doc: dict[str, Any]) -> datetime:
    value = doc["start_at"]
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=UTC)
    return value  # type: ignore[return-value]


_DOW_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def synthesize_recurring_session_docs(
    template_docs: list[dict[str, Any]],
    *,
    range_start: datetime,
    range_end: datetime,
    first_per_template: bool = False,
    local_start_date: date | None = None,
    local_end_date: date | None = None,
    filter_by_utc_range: bool = True,
) -> list[dict[str, Any]]:
    """Expand legacy recurring templates into dated read-model rows."""
    rows: list[dict[str, Any]] = []
    for template in template_docs:
        timezone_name = str(template.get("timezone") or "America/Chicago")
        tz = ZoneInfo(timezone_name)
        active_start = _coerce_template_date(template.get("start_date"))
        active_end = _coerce_template_date(template.get("end_date"))
        current_date = local_start_date or range_start.astimezone(tz).date()
        final_date = local_end_date or range_end.astimezone(tz).date()
        if active_start is not None:
            current_date = max(current_date, active_start)
        if active_end is not None:
            final_date = min(final_date, active_end)
        while current_date <= final_date:
            current_dow = current_date.weekday()
            dow_strs = list(template.get("days_of_week") or [])
            dow_ints = [_DOW_MAP[dow] for dow in dow_strs if dow in _DOW_MAP]
            if current_dow not in dow_ints:
                current_date += timedelta(days=1)
                continue
            st_str = str(template.get("start_time") or "00:00")
            et_str = str(template.get("end_time") or "00:00")
            start_at = datetime.combine(current_date, time.fromisoformat(st_str), tzinfo=tz)
            end_at = datetime.combine(current_date, time.fromisoformat(et_str), tzinfo=tz)
            start_at = start_at.astimezone(UTC)
            end_at = end_at.astimezone(UTC)
            if filter_by_utc_range and (start_at < range_start or start_at > range_end):
                current_date += timedelta(days=1)
                continue
            doc = dict(template)
            doc["start_at"] = start_at
            doc["end_at"] = end_at
            doc.setdefault("session_id", str(doc["_id"]))
            doc.setdefault("title", str(doc.get("name") or "Session"))
            doc.setdefault("capacity", doc.get("max_students", 15))
            rows.append(doc)
            if first_per_template:
                break
            current_date += timedelta(days=1)
    return rows


def _coerce_template_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return None


class MongoSessionRepository(TenantScopedRepository):
    collection_name = "sessions"

    def __init__(self, db: Any, *, default_amount_cents: int = 15000) -> None:
        super().__init__(db)
        self._default_amount_cents = default_amount_cents

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Session:
        status = str(doc.get("status") or "scheduled")
        if status in {"active", "open"}:
            status = "scheduled"
        start_at = doc.get("start_at")
        end_at = doc.get("end_at")
        if start_at is None or end_at is None:
            start_at, end_at = _representative_template_times(doc)
        # Normalise legacy schema (name/max_students) to v2 schema (title/capacity).
        return Session(
            session_id=str(doc.get("session_id") or doc.get("_id")),
            academy_id=str(doc.get("academy_id") or "default-academy"),
            coach_id=str(doc.get("coach_id") or ""),
            title=str(doc.get("title") or doc.get("name") or "Session"),
            location=str(doc.get("location") or ""),
            start_at=start_at,  # type: ignore[arg-type]
            end_at=end_at,  # type: ignore[arg-type]
            capacity=int(doc.get("capacity") or doc.get("max_students") or 15),  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            days_of_week=list(doc.get("days_of_week") or []),
            start_time=None if doc.get("start_time") is None else str(doc.get("start_time")),
            end_time=None if doc.get("end_time") is None else str(doc.get("end_time")),
            timezone=None if doc.get("timezone") is None else str(doc.get("timezone")),
        )

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        start, end = _day_bounds_utc(on_date)
        cursor = self._find_many(
            {"coach_id": coach_id, "start_at": {"$gte": start, "$lte": end}},
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def for_coach(self, coach_id: str) -> list[Session]:
        now = datetime.now(UTC)
        cursor = self._find_many(
            {"coach_id": coach_id, "start_at": {"$gte": now}},
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def get(self, session_id: str) -> Session | None:
        doc = await self._find_one(_session_filter(session_id))
        return self._to_domain(doc) if doc else None

    async def get_many(self, session_ids: list[str]) -> list[Session]:
        if not session_ids:
            return []
        cursor = self._find_many(_session_ids_filter(session_ids))
        return [self._to_domain(doc) async for doc in cursor]

    async def available_for_parent_catalog(self) -> list[ParentAvailableSession]:
        now = datetime.now(UTC)
        end = now + timedelta(days=30, hours=23, minutes=59, seconds=59, microseconds=999999)
        cursor = self._find_many(
            {
                "status": {"$nin": ["cancelled", "completed"]},
                "start_at": {"$gte": now, "$lte": end},
                "days_of_week": {"$exists": False},
            },
            sort=[("start_at", 1)],
        )
        docs = [doc async for doc in cursor]
        template_cursor = self._find_many(
            {
                "status": {"$nin": ["cancelled", "completed"]},
                "days_of_week": {"$exists": True},
            },
        )
        template_docs = [doc async for doc in template_cursor]
        seen_template_sessions: set[str] = set()
        for doc in synthesize_recurring_session_docs(
            template_docs,
            range_start=now,
            range_end=end,
            first_per_template=True,
        ):
            session_id = str(doc.get("session_id") or doc.get("_id"))
            if session_id in seen_template_sessions:
                continue
            seen_template_sessions.add(session_id)
            docs.append(doc)
        docs.sort(key=session_start_sort_key)
        rows: list[ParentAvailableSession] = []
        for doc in docs:
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
            if len(rows) >= 100:
                break
        return rows


def _amount_cents(doc: dict[str, object], default_amount_cents: int) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return default_amount_cents


def _representative_template_times(doc: dict[str, object]) -> tuple[datetime, datetime]:
    timezone_name = str(doc.get("timezone") or "America/Chicago")
    tz = ZoneInfo(timezone_name)
    current_date = datetime.now(UTC).astimezone(tz).date()
    active_start = _coerce_template_date(doc.get("start_date"))
    if active_start is not None:
        current_date = max(current_date, active_start)
    dow_strs = list(doc.get("days_of_week") or [])
    dow_ints = {_DOW_MAP[dow] for dow in dow_strs if dow in _DOW_MAP}
    if dow_ints:
        while current_date.weekday() not in dow_ints:
            current_date += timedelta(days=1)
    start_time = time.fromisoformat(str(doc.get("start_time") or "00:00"))
    end_time = time.fromisoformat(str(doc.get("end_time") or doc.get("start_time") or "00:00"))
    start_at = datetime.combine(current_date, start_time, tzinfo=tz).astimezone(UTC)
    end_at = datetime.combine(current_date, end_time, tzinfo=tz).astimezone(UTC)
    return start_at, end_at


def _session_filter(session_id: str) -> dict[str, object]:
    if ObjectId.is_valid(session_id):
        return {"$or": [{"session_id": session_id}, {"_id": ObjectId(session_id)}]}
    return {"session_id": session_id}


def _session_ids_filter(session_ids: list[str]) -> dict[str, object]:
    object_ids = [
        ObjectId(session_id) for session_id in session_ids if ObjectId.is_valid(session_id)
    ]
    filters: list[dict[str, object]] = [{"session_id": {"$in": session_ids}}]
    if object_ids:
        filters.append({"_id": {"$in": object_ids}})
    return {"$or": filters}
