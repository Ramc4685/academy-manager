"""Query: upcoming schedule for a child, as seen by a parent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    SessionOccurrenceRepository,
    SessionQuery,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry

#: Where a schedule row comes from: the child's standing enrollment, or a
#: one-time occurrence roster entry written by an approved make-up / trial
#: (issue #1038).
ScheduleEntrySource = Literal["regular", "makeup", "trial"]


class StudentNotOwnedByParent(Exception):
    """Raised when the requested student does not belong to the requesting parent."""


class _StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> object | None: ...


class _OccurrenceRosterQuery(Protocol):
    async def list_for_student(
        self, student_id: str, *, limit: int
    ) -> list[OccurrenceRosterEntry]: ...


class _OneTimeOccurrenceQuery(Protocol):
    """Batch read of specific occurrences, bounded to a start window."""

    async def list_by_ids_between(
        self, occurrence_ids: list[str], *, start_at: datetime, end_at: datetime
    ) -> list[SessionOccurrence]: ...


#: Cap on how many one-time roster rows one schedule read considers. The
#: newest rows are kept, so a long-enrolled child's old make-ups and trials
#: cannot make every schedule / Home load grow without bound.
ONE_TIME_ROSTER_READ_LIMIT = 200


class ChildScheduleEntry(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    coach_name: str | None = None
    source: ScheduleEntrySource = "regular"


class GetChildSchedule:
    """Upcoming classes for one child: standing enrollments AND one-time
    make-up / trial attendance (issue #1038).

    One-time rows come from ``occurrence_roster_entries`` — the same rows the
    coach roster reads — so the parent sees exactly the attendance plan the
    coach sees. Those rows are deleted when the class/session is cancelled
    (and the make-up re-opened) or the enrollment ends, and a row whose
    occurrence is cancelled or gone is hidden here exactly as
    ``GetOccurrenceRoster`` hides it, so a stale "attend here" never shows.

    Cancelled classes are intentionally treated differently by source. A
    regular row for a cancelled occurrence is kept (status ``cancelled``) so
    the family sees "Cancelled — this class will not run" for a class they
    attend every week. A one-time row is dropped instead: cancelling the
    class re-opens the make-up / trial request (#671, #694), so the family's
    next step is on the Requests page, and a cancelled one-off date would only
    sit next to the replacement date the academy offers.
    """

    def __init__(
        self,
        *,
        enrollments: EnrollmentQuery,
        occurrences: SessionOccurrenceRepository,
        sessions: SessionQuery,
        students: _StudentQuery,
        occurrence_roster: _OccurrenceRosterQuery | None = None,
        one_time_occurrences: _OneTimeOccurrenceQuery | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (occurrence_roster is None) != (one_time_occurrences is None):
            raise ValueError("occurrence_roster and one_time_occurrences must be wired together")
        self._enrollments = enrollments
        self._occurrence_roster = occurrence_roster
        self._one_time_occurrences_query = one_time_occurrences
        self._occurrences = occurrences
        self._sessions = sessions
        self._students = students
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        parent_id: str,
        student_id: str,
        *,
        frm: date | None,
        to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChildScheduleEntry], int]:
        """Return (page_entries, total_count) where total_count is the unsliced size."""
        student = await self._students.get_for_parent(parent_id, student_id)
        if student is None:
            raise StudentNotOwnedByParent(
                f"student {student_id!r} not found for parent {parent_id!r}"
            )

        now = self._clock()
        start_dt: datetime = (
            datetime(frm.year, frm.month, frm.day, 0, 0, 0, tzinfo=UTC) if frm is not None else now
        )
        end_dt: datetime = (
            datetime(to.year, to.month, to.day, tzinfo=UTC) + timedelta(days=1)
            if to is not None
            else now + timedelta(days=30)
        )

        active_enrollments = await self._enrollments.active_for_student(student_id)
        one_time_occurrences = await self._one_time_occurrences(student_id, start_dt, end_dt)
        if not active_enrollments and not one_time_occurrences:
            return [], 0

        # Batch-fetch all sessions in a single round-trip instead of one per enrollment.
        session_ids = list(
            dict.fromkeys(
                [e.session_id for e in active_enrollments]
                + [
                    sid
                    for occ, _source in one_time_occurrences
                    for sid in (occ.template_session_id, occ.session_id)
                    if sid
                ]
            )
        )
        sessions_map = {s.session_id: s for s in await self._sessions.get_many(session_ids)}

        all_entries: list[ChildScheduleEntry] = []
        seen_occurrence_ids: set[str] = set()

        for enrollment in active_enrollments:
            session_occs = await self._occurrences.list_for_session_between(
                session_id=enrollment.session_id,
                start_at=start_dt,
                end_at=end_dt,
            )
            session = sessions_map.get(enrollment.session_id)
            session_title = session.title if session else "Session"

            session_location = session.location if session else None
            for occ in session_occs:
                if occ.occurrence_id in seen_occurrence_ids:
                    continue
                seen_occurrence_ids.add(occ.occurrence_id)
                all_entries.append(
                    ChildScheduleEntry(
                        occurrence_id=occ.occurrence_id,
                        session_id=enrollment.session_id,
                        session_title=session_title,
                        location=session_location,
                        start_at=occ.start_at,
                        end_at=occ.end_at,
                        status=occ.status,
                        coach_name=None,
                    )
                )

        # One-time attendance. A regular row for the same occurrence wins: the
        # child is there either way, and the regular row is the durable one.
        for occ, source in one_time_occurrences:
            if occ.occurrence_id in seen_occurrence_ids:
                continue
            seen_occurrence_ids.add(occ.occurrence_id)
            session = next(
                (
                    sessions_map[sid]
                    for sid in (occ.template_session_id, occ.session_id)
                    if sid and sid in sessions_map
                ),
                None,
            )
            all_entries.append(
                ChildScheduleEntry(
                    occurrence_id=occ.occurrence_id,
                    session_id=session.session_id if session else occ.session_id,
                    session_title=session.title if session else "Session",
                    location=session.location if session else None,
                    start_at=occ.start_at,
                    end_at=occ.end_at,
                    status=occ.status,
                    coach_name=None,
                    source=source,
                )
            )

        all_entries.sort(key=lambda e: e.start_at)
        total = len(all_entries)
        return all_entries[offset : offset + limit], total

    async def _one_time_occurrences(
        self, student_id: str, start_dt: datetime, end_dt: datetime
    ) -> list[tuple[SessionOccurrence, ScheduleEntrySource]]:
        """The child's one-time (make-up / trial) occurrences inside the window.

        Reads are tenant-scoped by the repositories; the caller has already
        proven the child belongs to the requesting parent. Rows whose
        occurrence was cancelled or no longer exists are dropped (mirrors
        ``GetOccurrenceRoster``, issue #694).
        """
        if self._occurrence_roster is None or self._one_time_occurrences_query is None:
            return []
        entries = await self._occurrence_roster.list_for_student(
            student_id, limit=ONE_TIME_ROSTER_READ_LIMIT
        )
        if not entries:
            return []
        source_by_occurrence: dict[str, ScheduleEntrySource] = {}
        for entry in entries:
            source_by_occurrence.setdefault(entry.occurrence_id, entry.source)
        # Only occurrences that start inside the window are fetched.
        occurrences = await self._one_time_occurrences_query.list_by_ids_between(
            list(source_by_occurrence), start_at=start_dt, end_at=end_dt
        )
        result: list[tuple[SessionOccurrence, ScheduleEntrySource]] = []
        for occ in occurrences:
            # Dropped, not shown as cancelled: see the class docstring.
            if occ.status == "cancelled":
                continue
            if not (start_dt <= occ.start_at <= end_dt):
                continue
            source = source_by_occurrence.get(occ.occurrence_id)
            if source is None:
                continue
            result.append((occ, source))
        return result
