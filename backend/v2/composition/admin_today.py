"""Admin Today: today's classes with rosters for the dashboard (S63, D-20).

``GET /admin/today`` lists the academy's class dates on its own calendar day,
each with a roster (parent name and phone, attendance state) and the phase,
counts and "next" flag worked out here so the browser never reads the device
clock. **No health field rides on this payload**: the medical marker comes
only from ``GET /admin/today/roster-health``, through the same reader the
coach's S49 route uses (``composition/coach_roster_health.py``), so this read
is safe to refetch and keep in the query cache.

Page-scoped so ``composition/admin.py`` (at its line budget) is not touched.
Wired from ``main.py`` as ``app.state.admin_today``.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from bson import ObjectId
from pydantic import BaseModel

from backend.v2.composition.coach_roster_health import (
    RosterHealthReader,
    parent_ref,
    user_contacts,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    CoachOccurrenceForDate,
    ListCoachOccurrencesForDate,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.shared.tenancy.context import current_academy_id
from backend.v2.shared.time.academy_timezone import (
    academy_timezone_lookup,
    resolve_academy_clock_timezone,
)

Phase = Literal["now", "next", "later", "finished", "cancelled"]
RosterAttendance = Literal["present", "late", "absent"]


class TodayRosterRow(BaseModel):
    student_id: str
    full_name: str
    kind: Literal["enrolled", "makeup", "trial"]
    attendance: RosterAttendance | None = None
    expected_absent: bool = False
    parent_id: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None


class TodayClass(BaseModel):
    occurrence_id: str
    session_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    status: str
    cancellation_reason: str | None = None
    phase: Phase
    #: Whole minutes until the start, only for the NEXT class under an hour away.
    starts_in_minutes: int | None = None
    coach_id: str | None = None
    coach_name: str | None = None
    cover_coach_name: str | None = None
    #: Lead, cover and assistants: who "Running late" messages (S65).
    staff_ids: list[str] = []
    #: Filled by the coach cover flow (S67); false until it lands.
    cover_requested: bool = False
    enrolled_count: int
    here_count: int
    absent_count: int
    marked_count: int
    roster: list[TodayRosterRow]


class TodayTomorrow(BaseModel):
    class_count: int
    first_start_at: datetime | None = None


_ATTENDANCE: dict[str, RosterAttendance] = {
    "present": "present",
    "late": "late",
    "absent": "absent",
}


def _attendance(mark: str | None) -> RosterAttendance | None:
    """Excused and voided marks read as not marked on the Today roster."""
    return _ATTENDANCE.get(mark or "")


class PhoneMatch(BaseModel):
    parent_id: str
    name: str | None = None
    phone: str
    children: list[str]


def phone_digits(raw: str) -> str:
    """Digits of a typed phone, without a leading North American ``1``."""
    digits = re.sub(r"\D", "", raw)
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


class AdminToday(BaseModel):
    date: date
    timezone: str
    classes: list[TodayClass]
    tomorrow: TodayTomorrow
    #: Academy-inbox threads waiting on staff (S61); 0 until it lands.
    messages_waiting: int = 0
    #: D-14 accepted for every academy; there is no per-academy switch yet.
    health_enabled: bool = True


_KIND: dict[str, Literal["enrolled", "makeup", "trial"]] = {
    "enrollment": "enrolled",
    "makeup": "makeup",
    "trial": "trial",
}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def class_phases(
    classes: list[CoachOccurrenceForDate], *, now: datetime, is_today: bool
) -> dict[str, tuple[Phase, int | None]]:
    """NOW / NEXT / LATER / FINISHED / CANCELLED per class, from the server clock.

    Only one class is NEXT: the earliest not-yet-started, not-cancelled class
    of today. Every other future class is LATER (all of them on another day).
    """
    out: dict[str, tuple[Phase, int | None]] = {}
    upcoming = sorted(
        (c for c in classes if c.status != "cancelled" and _utc(c.start_at) > now),
        key=lambda c: _utc(c.start_at),
    )
    next_id = upcoming[0].occurrence_id if is_today and upcoming else None
    for c in classes:
        start, end = _utc(c.start_at), _utc(c.end_at)
        if c.status == "cancelled":
            out[c.occurrence_id] = ("cancelled", None)
        elif now >= end:
            out[c.occurrence_id] = ("finished", None)
        elif now >= start:
            out[c.occurrence_id] = ("now", None)
        elif c.occurrence_id == next_id:
            minutes = math.ceil((start - now).total_seconds() / 60)
            out[c.occurrence_id] = ("next", minutes if minutes < 60 else None)
        else:
            out[c.occurrence_id] = ("later", None)
    return out


@dataclass
class AdminTodayReader:
    db: Any
    health: RosterHealthReader
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        self._occurrences = MongoSessionOccurrenceRepository(self.db)
        self._list = ListCoachOccurrencesForDate(
            occurrences=self._occurrences, sessions=MongoSessionRepository(self.db)
        )
        self._marks = MongoAttendanceRepository(self.db)
        self._timezone = academy_timezone_lookup(self.db)

    async def today(self, on_date: date | None = None) -> AdminToday:
        academy_id = current_academy_id()
        zone = await resolve_academy_clock_timezone(self._timezone, academy_id)
        now = _utc(self.clock())
        local_today = now.astimezone(ZoneInfo(zone)).date()
        target = on_date or local_today

        classes = await self._list.execute_for_academy(target, include_cancelled=True)
        classes.sort(key=lambda c: (_utc(c.start_at), c.title))
        occurrence_ids = [c.occurrence_id for c in classes]
        stored, rosters, marks, tomorrow = await asyncio.gather(
            self._occurrences.get_many(occurrence_ids),
            asyncio.gather(
                *(
                    self.health.roster.execute(
                        session_id=c.roster_session_id, occurrence_id=c.occurrence_id
                    )
                    for c in classes
                )
            ),
            self._marks.list_for_occurrences(occurrence_ids),
            self._list.execute_for_academy(target + timedelta(days=1)),
        )
        staff = {o.occurrence_id: o for o in stored}
        marks_by: dict[tuple[str, str], str] = {
            (m.occurrence_id, m.student_id): m.status for m in marks if m.status != "voided"
        }
        student_ids = sorted({r.student_id for roster in rosters for r in roster})
        parents_of = await self._parent_ids(student_ids)
        coach_ids = [
            uid
            for o in stored
            for uid in (o.actual_coach_id or o.scheduled_coach_id, o.substitute_coach_id)
            if uid
        ]
        people = await user_contacts(self.db, [*parents_of.values(), *coach_ids])
        phases = class_phases(classes, now=now, is_today=target == local_today)

        out: list[TodayClass] = []
        for c, roster in zip(classes, rosters, strict=True):
            occ = staff.get(c.occurrence_id)
            lead = (occ.actual_coach_id or occ.scheduled_coach_id) if occ else c.coach_id
            cover = occ.substitute_coach_id if occ else None
            assistants = list(occ.assistant_coach_ids) if occ else []
            staff_ids = list(dict.fromkeys(uid for uid in (lead, cover, *assistants) if uid))
            rows: list[TodayRosterRow] = []
            for r in roster:
                parent_id = parents_of.get(r.student_id) or None
                parent = people.get(parent_id or "", {})
                mark = marks_by.get((c.occurrence_id, r.student_id))
                rows.append(
                    TodayRosterRow(
                        student_id=r.student_id,
                        full_name=r.full_name,
                        kind=_KIND.get(r.entry_source, "enrolled"),
                        attendance=_attendance(mark),
                        expected_absent=r.expected_absence,
                        parent_id=parent_id,
                        parent_name=parent.get("name"),
                        parent_phone=parent.get("phone"),
                    )
                )
            rows.sort(key=lambda row: (row.full_name.casefold(), row.student_id))
            phase, minutes = phases[c.occurrence_id]
            out.append(
                TodayClass(
                    occurrence_id=c.occurrence_id,
                    session_id=c.session_id,
                    title=c.title,
                    location=c.location,
                    start_at=c.start_at,
                    end_at=c.end_at,
                    status=c.status,
                    cancellation_reason=c.cancellation_reason,
                    phase=phase,
                    starts_in_minutes=minutes,
                    coach_id=lead,
                    coach_name=people.get(lead or "", {}).get("name"),
                    cover_coach_name=people.get(cover, {}).get("name") if cover else None,
                    staff_ids=staff_ids,
                    enrolled_count=len(rows),
                    here_count=sum(1 for row in rows if row.attendance in ("present", "late")),
                    absent_count=sum(1 for row in rows if row.attendance == "absent"),
                    marked_count=sum(1 for row in rows if row.attendance is not None),
                    roster=rows,
                )
            )
        tomorrow_starts = sorted(_utc(c.start_at) for c in tomorrow if c.status != "cancelled")
        return AdminToday(
            date=target,
            timezone=zone,
            classes=out,
            tomorrow=TodayTomorrow(
                class_count=len(tomorrow_starts),
                first_start_at=tomorrow_starts[0] if tomorrow_starts else None,
            ),
        )

    async def parents_by_phone(self, digits: str, *, limit: int = 10) -> list[PhoneMatch]:
        """Parents of this academy's students whose phone contains ``digits``.

        Users are global, so the academy's own student rows decide who counts
        as one of its parents; the phone filter then runs on those ids only.
        """
        children: dict[str, list[str]] = {}
        cursor = self.db["students"].find(
            {"academy_id": current_academy_id()},
            {"full_name": 1, "first_name": 1, "last_name": 1, "parent_id": 1, "parent_user_id": 1},
        )
        async for doc in cursor:
            parent_id = parent_ref(doc)
            name = str(doc.get("full_name") or "").strip() or (
                f"{doc.get('first_name') or ''} {doc.get('last_name') or ''}".strip()
            )
            if parent_id and name:
                children.setdefault(parent_id, []).append(name)
        if not children:
            return []
        ids = list(children)
        object_ids = [ObjectId(uid) for uid in ids if ObjectId.is_valid(uid)]
        # Digits only, so the pattern is safe; \D* skips the stored formatting.
        pattern = r"\D*".join(digits)
        users = self.db["users"].find(
            {
                "$or": [{"user_id": {"$in": ids}}, {"_id": {"$in": object_ids}}],
                "phone": {"$regex": pattern},
            },
            {"user_id": 1, "display_name": 1, "first_name": 1, "last_name": 1, "phone": 1},
        )
        matches: list[PhoneMatch] = []
        async for user in users:
            key = str(user.get("user_id") or user.get("_id"))
            kids = children.get(key) or children.get(str(user.get("_id")), [])
            name = str(user.get("display_name") or "").strip() or (
                f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
            )
            matches.append(
                PhoneMatch(
                    parent_id=key,
                    name=name or None,
                    phone=str(user.get("phone") or ""),
                    children=sorted(set(kids), key=str.casefold),
                )
            )
        matches.sort(key=lambda m: ((m.name or "").casefold(), m.parent_id))
        return matches[:limit]

    async def _parent_ids(self, student_ids: list[str]) -> dict[str, str]:
        if not student_ids:
            return {}
        cursor = self.db["students"].find(
            {"academy_id": current_academy_id(), "student_id": {"$in": student_ids}},
            {"student_id": 1, "parent_id": 1, "parent_user_id": 1},
        )
        return {str(doc["student_id"]): parent_ref(doc) async for doc in cursor}


def compose_admin_today(db: Any, *, health: RosterHealthReader) -> AdminTodayReader:
    return AdminTodayReader(db=db, health=health)
