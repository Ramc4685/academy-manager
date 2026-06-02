"""Query: upcoming schedule for a child, as seen by a parent."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    SessionOccurrenceRepository,
    SessionQuery,
)


class StudentNotOwnedByParent(Exception):
    """Raised when the requested student does not belong to the requesting parent."""


class _StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> object | None: ...


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


class GetChildSchedule:
    def __init__(
        self,
        *,
        enrollments: EnrollmentQuery,
        occurrences: SessionOccurrenceRepository,
        sessions: SessionQuery,
        students: _StudentQuery,
    ) -> None:
        self._enrollments = enrollments
        self._occurrences = occurrences
        self._sessions = sessions
        self._students = students

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

        now = datetime.now(UTC)
        start_dt: datetime = (
            datetime(frm.year, frm.month, frm.day, 0, 0, 0, tzinfo=UTC) if frm is not None else now
        )
        end_dt: datetime = (
            datetime(to.year, to.month, to.day, tzinfo=UTC) + timedelta(days=1)
            if to is not None
            else now + timedelta(days=30)
        )

        active_enrollments = await self._enrollments.active_for_student(student_id)
        if not active_enrollments:
            return [], 0

        # Batch-fetch all sessions in a single round-trip instead of one per enrollment.
        session_ids = [e.session_id for e in active_enrollments]
        sessions_map = {s.session_id: s for s in await self._sessions.get_many(session_ids)}

        all_entries: list[ChildScheduleEntry] = []

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

        all_entries.sort(key=lambda e: e.start_at)
        total = len(all_entries)
        return all_entries[offset : offset + limit], total
