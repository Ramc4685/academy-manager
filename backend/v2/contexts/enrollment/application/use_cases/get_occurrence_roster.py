"""Query: occurrence-scoped roster, with expected-absence flags and
one-time (makeup/trial) entries merged in.

``GetSessionRoster`` is session-scoped and has several callers (skill
routes, billing enrollment routes, the daily teaching plan) that must not
change shape. Coach-today, by contrast, needs a per-*occurrence* view: each
rendered occurrence should show which enrolled students gave advance notice
of absence (Task 2's AbsenceNotice) and which one-time students (makeup/
trial approvals — Tasks 5/7) were added just for this occurrence. This use
case composes ``GetSessionRoster``'s output with those two extra reads
rather than forking or reshaping it.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import StudentQuery
from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.domain.models import EnrollmentStatus
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry

EntrySource = Literal["enrollment", "makeup", "trial"]


class OccurrenceRosterItem(BaseModel):
    """A single roster row for one occurrence, ready for BFF view-mapping."""

    model_config = {"frozen": True}

    # None for one-time (makeup/trial) entries — they have no standing
    # enrollment. Enrollment-backed rows always set this.
    enrollment_id: str | None
    student_id: str
    full_name: str
    status: EnrollmentStatus | None
    entry_source: EntrySource
    expected_absence: bool


class AbsenceNoticeQuery(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[AbsenceNotice]: ...


class OccurrenceRosterQuery(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]: ...


class GetOccurrenceRoster:
    def __init__(
        self,
        *,
        get_roster: GetSessionRoster,
        absence_notices: AbsenceNoticeQuery,
        occurrence_roster: OccurrenceRosterQuery,
        students: StudentQuery,
    ) -> None:
        self._get_roster = get_roster
        self._absence_notices = absence_notices
        self._occurrence_roster = occurrence_roster
        # Same student query GetSessionRoster uses internally, so one-time
        # entries resolve full_name the same way regular roster entries do.
        self._students = students

    async def execute(self, *, session_id: str, occurrence_id: str) -> list[OccurrenceRosterItem]:
        roster = await self._get_roster.execute(session_id)
        notices = await self._absence_notices.list_for_occurrence(occurrence_id)
        absent_student_ids = {n.student_id for n in notices}

        out: list[OccurrenceRosterItem] = [
            OccurrenceRosterItem(
                enrollment_id=entry.enrollment_id,
                student_id=entry.student_id,
                full_name=entry.full_name,
                status=entry.status,
                entry_source="enrollment",
                expected_absence=entry.student_id in absent_student_ids,
            )
            for entry in roster
        ]

        one_time_entries = await self._occurrence_roster.list_for_occurrence(occurrence_id)
        if one_time_entries:
            students = await self._students.by_ids([e.student_id for e in one_time_entries])
            students_by_id = {s.student_id: s for s in students}
            for entry in one_time_entries:
                student = students_by_id.get(entry.student_id)
                if student is None:
                    # Orphan one-time entry — skip, mirroring GetSessionRoster's
                    # orphan-enrollment handling. Logged out-of-band.
                    continue
                out.append(
                    OccurrenceRosterItem(
                        enrollment_id=None,
                        student_id=student.student_id,
                        full_name=student.full_name,
                        status=None,
                        entry_source=entry.source,
                        expected_absence=student.student_id in absent_student_ids,
                    )
                )
        return out
