"""Mongo SessionQuery."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ParentAvailableSession,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import academy_timezone_lookup, ensure_utc


def _day_bounds_utc(on_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on_date, time.min, tzinfo=UTC)
    end = datetime.combine(on_date, time.max, tzinfo=UTC)
    return start, end


log = logging.getLogger(__name__)

# Last-resort zone for LEGACY rows that carry neither their own `timezone` nor
# a resolvable tenant zone. Reads must never raise, so this rung stays — but it
# is a single-tenant guess, so reaching it is logged rather than silent. Writes
# fail closed instead (see admin_writes._resolve_session_timezone).
LEGACY_FALLBACK_TIMEZONE = "America/Chicago"


def _template_timezone(template: dict[str, Any], fallback: str | None) -> str:
    explicit = str(template.get("timezone") or "").strip()
    if explicit:
        return explicit
    resolved = str(fallback or "").strip()
    if resolved:
        return resolved
    log.warning(
        "Session template %s has no timezone and no academy timezone; "
        "falling back to %s. Occurrence times may be wrong.",
        template.get("session_id") or template.get("_id"),
        LEGACY_FALLBACK_TIMEZONE,
    )
    return LEGACY_FALLBACK_TIMEZONE


def session_start_sort_key(doc: dict[str, Any]) -> datetime:
    return ensure_utc(doc["start_at"])


_DOW_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAY_INDEX = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _normalized_series_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _canonical_weekdays(days: object) -> tuple[str, ...]:
    values = list(days or []) if isinstance(days, list) else []
    canonical: set[str] = set()
    passthrough: set[str] = set()
    for day in values:
        raw = str(day).strip()
        index = WEEKDAY_INDEX.get(raw.casefold())
        if index is None:
            if raw:
                passthrough.add(raw)
            continue
        canonical.add(WEEKDAY_NAMES[index])
    return tuple(sorted(canonical, key=lambda day: WEEKDAY_NAMES.index(day)) + sorted(passthrough))


def _series_local_clock_signature(
    row: dict[str, Any], fallback_timezone: str | None
) -> tuple[tuple[str, ...], str, str, str] | None:
    # Two rows only describe the same series if they share a wall clock, so the
    # zone is part of the signature. It used to default to a hardcoded
    # "America/Chicago", which silently merged two genuinely different series
    # for any tenant not in that zone; resolve the tenant's own zone instead.
    timezone_name = _template_timezone(row, fallback_timezone)
    days = list(row.get("days_of_week") or [])
    if days and row.get("start_time") and row.get("end_time"):
        return (
            _canonical_weekdays(days),
            str(row.get("start_time") or ""),
            str(row.get("end_time") or ""),
            timezone_name,
        )

    start_at = row.get("start_at")
    end_at = row.get("end_at")
    if not start_at or not end_at:
        return None
    tz = ZoneInfo(timezone_name)
    local_start = ensure_utc(start_at).astimezone(tz)
    local_end = ensure_utc(end_at).astimezone(tz)
    weekday = WEEKDAY_NAMES[local_start.weekday()]
    return (
        (weekday,),
        local_start.strftime("%H:%M"),
        local_end.strftime("%H:%M"),
        timezone_name,
    )


def session_series_signature(
    row: dict[str, Any], fallback_timezone: str | None
) -> tuple[object, ...] | None:
    clock_signature = _series_local_clock_signature(row, fallback_timezone)
    if clock_signature is None:
        return None
    days, start_time_value, end_time_value, timezone_name = clock_signature
    return (
        _normalized_series_text(row.get("location")),
        str(row.get("coach_id") or ""),
        days,
        start_time_value,
        end_time_value,
        timezone_name,
    )


def _recurring_row_rank(row: dict[str, Any]) -> tuple[int, int, float]:
    return (
        int(row.get("enrolled_count") or 0),
        int(row.get("waitlist_count") or 0),
        -ensure_utc(row["start_at"]).timestamp(),
    )


def dedupe_session_series_rows(
    rows: list[dict[str, Any]], *, fallback_timezone: str | None = None
) -> list[dict[str, Any]]:
    """Collapse rows that describe the same recurring series to the best one."""
    deduped: list[dict[str, Any]] = []
    index_by_signature: dict[tuple[object, ...], int] = {}
    for row in rows:
        signature = session_series_signature(row, fallback_timezone)
        if signature is None:
            deduped.append(row)
            continue
        existing_index = index_by_signature.get(signature)
        if existing_index is None:
            index_by_signature[signature] = len(deduped)
            deduped.append(row)
            continue
        existing = deduped[existing_index]
        if _recurring_row_rank(row) > _recurring_row_rank(existing):
            deduped[existing_index] = row
    return deduped


def synthesize_recurring_session_docs(
    template_docs: list[dict[str, Any]],
    *,
    range_start: datetime,
    range_end: datetime,
    first_per_template: bool = False,
    local_start_date: date | None = None,
    local_end_date: date | None = None,
    filter_by_utc_range: bool = True,
    fallback_timezone: str | None = None,
) -> list[dict[str, Any]]:
    """Expand legacy recurring templates into dated read-model rows."""
    rows: list[dict[str, Any]] = []
    for template in template_docs:
        # A cancelled template has no live occurrences: cancel is a soft delete
        # (status="cancelled", doc retained), so never synthesize rows for it.
        if str(template.get("status") or "scheduled") == "cancelled":
            continue
        timezone_name = _template_timezone(template, fallback_timezone)
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
            # Record the zone the instants were actually computed in, so a
            # template with no `timezone` still tells consumers which zone its
            # wall-clock start_time was interpreted as.
            doc["timezone"] = timezone_name
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
            start_at=start_at,
            end_at=end_at,
            capacity=int(doc.get("capacity") or doc.get("max_students") or 15),
            amount_cents=_optional_amount_cents(doc),
            status=status,
            days_of_week=list(doc.get("days_of_week") or []),
            start_time=None if doc.get("start_time") is None else str(doc.get("start_time")),
            end_time=None if doc.get("end_time") is None else str(doc.get("end_time")),
            timezone=None if doc.get("timezone") is None else str(doc.get("timezone")),
            assistant_coach_ids=_string_tuple(doc.get("assistant_coach_ids")),
            # Communication pack (#613). This constructor is explicit, so a
            # field missing here is dropped on EVERY domain read — the admin
            # detail route, the coach views, and the welcome email's own
            # session lookup.
            whatsapp_group_link=_optional_str(doc.get("whatsapp_group_link")),
            venue_address=_optional_str(doc.get("venue_address")),
            parking_notes=_optional_str(doc.get("parking_notes")),
            what_to_bring=_optional_str(doc.get("what_to_bring")),
            arrival_minutes_before=_optional_int(doc.get("arrival_minutes_before")),
            coach_contact_policy=_optional_str(doc.get("coach_contact_policy")),
            absence_policy=_optional_str(doc.get("absence_policy")),
        )

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        start, end = _day_bounds_utc(on_date)
        cursor = self._find_many(
            {**_coach_or_assistant_filter(coach_id), "start_at": {"$gte": start, "$lte": end}},
            sort=[("start_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def assigned_session_ids_for_coach(
        self, coach_id: str, *, include_assistant: bool = True
    ) -> list[str]:
        """Every session assigned to this coach, with no date window at all.

        ``include_assistant`` (default) also counts sessions whose
        ``assistant_coach_ids`` list the user, matching
        ``CoachAssignedSessionLookup``. Pass ``False`` for audiences an
        assistant is NOT part of — the coach messages inbox (#614) — so a
        helper never receives family messages for a class they only assist.

        `for_coach` answers "what is coming up" (`start_at >= now`) and is the
        wrong question for anything about *assignment*: a recurring template
        stores one `start_at` computed when the series was created, so a
        Tue/Thu class started two months ago is permanently in the past by
        that filter while still running. Announcement visibility must agree
        with `CoachAssignedSessionLookup.is_coach_assigned`, which gates on
        `coach_id` alone — otherwise a coach can post to a session whose
        announcements they can never read.
        """
        query = (
            _coach_or_assistant_filter(coach_id) if include_assistant else {"coach_id": coach_id}
        )
        cursor = self._find_many_in_collection(self.collection_name, query, {"session_id": 1})
        return sorted({str(doc["session_id"]) async for doc in cursor if doc.get("session_id")})

    async def for_coach(self, coach_id: str) -> list[Session]:
        now = datetime.now(UTC)
        cursor = self._find_many(
            {**_coach_or_assistant_filter(coach_id), "start_at": {"$gte": now}},
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
        academy_timezone = await academy_timezone_lookup(self._db)(current_academy_id())
        seen_template_sessions: set[str] = set()
        for doc in synthesize_recurring_session_docs(
            template_docs,
            range_start=now,
            range_end=end,
            first_per_template=True,
            fallback_timezone=academy_timezone,
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
                    start_at=ensure_utc(doc["start_at"]),
                    end_at=ensure_utc(doc["end_at"]),
                    timezone=(str(doc["timezone"]).strip() or None)
                    if doc.get("timezone")
                    else None,
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
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return default_amount_cents


def _coach_or_assistant_filter(coach_id: str) -> dict[str, object]:
    """Sessions this user coaches: primary coach OR listed assistant coach.

    Mongo matches an array field against a scalar when any element equals it,
    so ``{"assistant_coach_ids": coach_id}`` is the membership test.
    """
    return {"$or": [{"coach_id": coach_id}, {"assistant_coach_ids": coach_id}]}


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if item)


def _optional_str(value: object) -> str | None:
    """Communication-pack text as stored, with blank treated as unset.

    A legacy or hand-edited doc can carry `""`; the whole feature keys off
    "populated means render this section", so an empty string must read the
    same as a missing key.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    return None


def admin_session_projection_fields(doc: dict[str, object]) -> dict[str, object | None]:
    """The read-model fields the admin session projection cannot hand-write safely.

    ``composition/admin.py::_build_admin_session_rows`` builds its row dict by
    hand, and a field left out of it is invisible: the view defaults it to
    None, so the value looks correct in the POST/PATCH response (rendered from
    the aggregate) and silently reverts on the next GET. That is exactly bug
    #609 for ``amount_cents``. Keeping these here — beside ``_to_domain``, the
    other doc->model mapper — means one place to add a field to.
    """
    return {
        # Legacy docs carry monthly_price_cents / monthly_price, so a bare
        # doc.get("amount_cents") is NOT equivalent (#609).
        "amount_cents": _optional_amount_cents(doc),
        # Assistant coaches; names are resolved by the admin composition.
        "assistant_coach_ids": list(_string_tuple(doc.get("assistant_coach_ids"))),
        # Communication pack (#613).
        "whatsapp_group_link": _optional_str(doc.get("whatsapp_group_link")),
        "venue_address": _optional_str(doc.get("venue_address")),
        "parking_notes": _optional_str(doc.get("parking_notes")),
        "what_to_bring": _optional_str(doc.get("what_to_bring")),
        "arrival_minutes_before": _optional_int(doc.get("arrival_minutes_before")),
        "coach_contact_policy": _optional_str(doc.get("coach_contact_policy")),
        "absence_policy": _optional_str(doc.get("absence_policy")),
    }


def _optional_amount_cents(doc: dict[str, object]) -> int | None:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return None


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
