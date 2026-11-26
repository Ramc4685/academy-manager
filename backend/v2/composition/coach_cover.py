"""Cover for a coach who cannot teach (S66, S67; docs/design/coach-sick.md).

The front desk's "Coach is sick" flow reads, per class date: who is scheduled,
the families on the roster, and which coaches are free (not teaching then) or
busy. There is no availability calendar: "free" means only "not on another
class date that overlaps". A coach's "I can't make it" (S67) is one message in
the academy inbox and nothing else.

Page-scoped so ``composition/admin.py`` (at its line budget) stays untouched;
wired from ``main.py`` as ``app.state.coach_cover``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.composition.coach_roster_health import RosterHealthReader, parent_ref
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
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

#: How far ahead "Coach is sick" lists a coach's class dates.
COVER_WINDOW = timedelta(days=14)
COVER_REQUEST_SCOPE = "cover_request"


@dataclass(frozen=True)
class Candidate:
    coach_id: str
    name: str


@dataclass(frozen=True)
class BusyCandidate:
    coach_id: str
    name: str
    class_title: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class CoverFamily:
    parent_id: str
    family_name: str
    has_email: bool


@dataclass(frozen=True)
class CoverOptions:
    occurrence: SessionOccurrence
    title: str
    scheduled_coach_id: str
    scheduled_coach_name: str | None
    enrolled_count: int
    families: list[CoverFamily]
    free: list[Candidate]
    busy: list[BusyCandidate]


@dataclass(frozen=True)
class CoachClassDate:
    occurrence_id: str
    session_id: str
    title: str
    start_at: datetime
    end_at: datetime
    enrolled_count: int


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def teaching_coach(occurrence: SessionOccurrence) -> str:
    """Who teaches the date: the cover, else the actual coach, else the scheduled one."""
    return (
        occurrence.substitute_coach_id
        or occurrence.actual_coach_id
        or occurrence.scheduled_coach_id
    )


def staff_of(occurrence: SessionOccurrence) -> set[str]:
    return {
        uid
        for uid in (
            occurrence.scheduled_coach_id,
            occurrence.actual_coach_id,
            occurrence.substitute_coach_id,
            *occurrence.assistant_coach_ids,
        )
        if uid
    }


def overlaps(a: SessionOccurrence, b: SessionOccurrence) -> bool:
    return _utc(a.start_at) < _utc(b.end_at) and _utc(b.start_at) < _utc(a.end_at)


def _by_name(c: Candidate | BusyCandidate) -> tuple[str, str]:
    return (c.name.casefold(), c.coach_id)


def split_free_busy(
    target: SessionOccurrence,
    candidates: Sequence[Candidate],
    others: Sequence[SessionOccurrence],
    titles: dict[str, str],
) -> tuple[list[Candidate], list[BusyCandidate]]:
    """Free and busy coaches for ``target``.

    The scheduled coach, the actual coach and the current cover are never
    offered. A candidate is busy when a non-cancelled class date other than
    ``target`` overlaps it and they are its scheduled, actual or cover coach
    or an assistant on it. Everyone else is free.
    """
    excluded = {target.scheduled_coach_id, target.actual_coach_id, target.substitute_coach_id}
    clashes = [
        o
        for o in others
        if o.occurrence_id != target.occurrence_id
        and o.status != "cancelled"
        and overlaps(o, target)
    ]
    free: list[Candidate] = []
    busy: list[BusyCandidate] = []
    for c in candidates:
        if c.coach_id in excluded:
            continue
        clash = next((o for o in clashes if c.coach_id in staff_of(o)), None)
        if clash is None:
            free.append(c)
        else:
            busy.append(
                BusyCandidate(
                    coach_id=c.coach_id,
                    name=c.name,
                    class_title=titles.get(clash.template_session_id or clash.session_id, ""),
                    start_at=clash.start_at,
                    end_at=clash.end_at,
                )
            )
    return sorted(free, key=_by_name), sorted(busy, key=_by_name)


class CoverNotFound(LookupError):
    """No such class date in this academy."""


@dataclass
class CoachCoverReader:
    db: Any
    health: RosterHealthReader

    def __post_init__(self) -> None:
        self._occurrences = MongoSessionOccurrenceRepository(self.db)
        self._sessions = MongoSessionRepository(self.db)

    async def when(self, occurrence: SessionOccurrence) -> tuple[str, str]:
        """``("Tue, Dec 8", "5:30 PM")`` on the academy's clock."""
        zone = await resolve_academy_clock_timezone(
            academy_timezone_lookup(self.db), current_academy_id()
        )
        local = _utc(occurrence.start_at).astimezone(ZoneInfo(zone))
        return (
            f"{local:%a}, {local:%b} {local.day}",
            f"{local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}",
        )

    async def occurrence(self, occurrence_id: str) -> SessionOccurrence | None:
        return await self._occurrences.get(occurrence_id)

    async def title(self, occurrence: SessionOccurrence) -> str:
        session = await self._sessions.get(occurrence.template_session_id or occurrence.session_id)
        return str(getattr(session, "title", "") or "")

    async def _roster_ids(self, occurrence: SessionOccurrence) -> list[str]:
        rows = await self.health.roster.execute(
            session_id=occurrence.template_session_id or occurrence.session_id,
            occurrence_id=occurrence.occurrence_id,
        )
        return [r.student_id for r in rows]

    async def coach_dates(self, coach_id: str, *, now: datetime) -> list[CoachClassDate]:
        """The coach's non-cancelled class dates from now to two weeks out."""
        rows = await self._occurrences.list_for_coach_upcoming(coach_id=coach_id, now=now)
        out: list[CoachClassDate] = []
        for o in rows:
            if _utc(o.start_at) >= now + COVER_WINDOW:
                continue
            out.append(
                CoachClassDate(
                    occurrence_id=o.occurrence_id,
                    session_id=o.template_session_id or o.session_id,
                    title=await self.title(o),
                    start_at=o.start_at,
                    end_at=o.end_at,
                    enrolled_count=len(await self._roster_ids(o)),
                )
            )
        return out

    async def _clashing(self, target: SessionOccurrence) -> list[SessionOccurrence]:
        # Class dates starting up to a day before the target and before it ends.
        return await self._occurrences.list_between(
            start_at=_utc(target.start_at) - timedelta(days=1), end_at=_utc(target.end_at)
        )

    async def options(self, occurrence_id: str, candidates: Sequence[Candidate]) -> CoverOptions:
        target = await self._occurrences.get(occurrence_id)
        if target is None:
            raise CoverNotFound(occurrence_id)
        others = await self._clashing(target)
        titles: dict[str, str] = {}
        for o in others:
            sid = o.template_session_id or o.session_id
            if sid not in titles:
                session = await self._sessions.get(sid)
                titles[sid] = str(getattr(session, "title", "") or "")
        free, busy = split_free_busy(target, candidates, others, titles)
        student_ids = await self._roster_ids(target)
        names = await user_facts(self.db, [target.scheduled_coach_id])
        return CoverOptions(
            occurrence=target,
            title=await self.title(target),
            scheduled_coach_id=target.scheduled_coach_id,
            scheduled_coach_name=names.get(target.scheduled_coach_id, {}).get("name"),
            enrolled_count=len(student_ids),
            families=await self._families(student_ids),
            free=free,
            busy=busy,
        )

    async def is_free(
        self, target: SessionOccurrence, coach_id: str, candidates: Sequence[Candidate]
    ) -> bool:
        """The write-time re-check: an active coach, not this date's own coach
        or cover, and not teaching then."""
        free, _ = split_free_busy(target, candidates, await self._clashing(target), {})
        return any(c.coach_id == coach_id for c in free)

    async def _families(self, student_ids: list[str]) -> list[CoverFamily]:
        if not student_ids:
            return []
        cursor = self.db["students"].find(
            {"academy_id": current_academy_id(), "student_id": {"$in": student_ids}},
            {"student_id": 1, "parent_id": 1, "parent_user_id": 1},
        )
        parent_ids = sorted({p async for doc in cursor if (p := parent_ref(doc))})
        facts = await user_facts(self.db, parent_ids)
        families = [
            CoverFamily(
                parent_id=pid,
                family_name=facts.get(pid, {}).get("name") or "A family",
                has_email=bool(facts.get(pid, {}).get("email")),
            )
            for pid in parent_ids
        ]
        return sorted(families, key=lambda f: (f.family_name.casefold(), f.parent_id))


async def user_facts(db: Any, user_ids: Sequence[str]) -> dict[str, dict[str, str | None]]:
    """``{user id: {"name", "email"}}`` for ids taken from tenant-scoped rows."""
    ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return {}
    object_ids = [ObjectId(uid) for uid in ids if ObjectId.is_valid(uid)]
    cursor = db["users"].find(
        {"$or": [{"user_id": {"$in": ids}}, {"_id": {"$in": object_ids}}]},
        {"user_id": 1, "display_name": 1, "first_name": 1, "last_name": 1, "email": 1},
    )
    out: dict[str, dict[str, str | None]] = {}
    async for user in cursor:
        name = str(user.get("display_name") or "").strip() or (
            f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
        )
        facts = {"name": name or None, "email": str(user.get("email") or "").strip() or None}
        for key in (user.get("user_id"), user.get("_id")):
            if key:
                out[str(key)] = facts
    return out


def cover_notice(*, title: str, day: str, time: str, cover: str, coach: str) -> str:
    """The families' cover notice (coach-sick.md section 6)."""
    return (
        f"{title} on {day} at {time} will be taught by Coach {cover} instead of "
        f"Coach {coach}. Same time, same place."
    )


def compose_coach_cover(db: Any, *, health: RosterHealthReader) -> CoachCoverReader:
    return CoachCoverReader(db=db, health=health)
