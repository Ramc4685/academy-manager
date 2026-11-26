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

The roster is the one *for that occurrence's date*, not today's: a child
whose enrollment began after the class ended is left out, and any child who
already has a mark for the occurrence stays on it (a withdrawn child's mark
does not vanish with their enrollment).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    SessionOccurrenceRepository,
    StudentQuery,
)
from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.domain.models import EnrollmentStatus, age_in_years
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry

EntrySource = Literal["enrollment", "makeup", "trial"]


class OccurrenceRosterItem(BaseModel):
    """A single roster row for one occurrence, ready for BFF view-mapping."""

    model_config = {"frozen": True}

    # None for one-time (makeup/trial) entries — they have no standing
    # enrollment — and for a marked child who has since left the class (kept
    # so the past register stays whole). Other enrollment rows set this.
    enrollment_id: str | None
    student_id: str
    full_name: str
    status: EnrollmentStatus | None
    entry_source: EntrySource
    expected_absence: bool
    # Issue #675: a parent's end-of-period cancel is pending; the student
    # keeps attending until this instant. Rosters stay status-only.
    pending_cancellation_at: datetime | None = None
    # Issue #773: GetSessionRoster already reads this off the enrollment; it
    # was simply dropped here, so the coach saw a held student with no hint
    # that the seat is on hold or when they come back.
    hold_return_on: date | None = None
    # People CRM L3a: a trial row carries its trial request id so the coach
    # can record Came / Didn't come, and the outcome already recorded (None
    # while unmarked). Both None on every other row.
    trial_request_id: str | None = None
    trial_outcome: str | None = None
    # Whole years; the date of birth itself never leaves the server.
    age_years: int | None = None


class AbsenceNoticeQuery(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[AbsenceNotice]: ...


class OccurrenceRosterQuery(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]: ...


class MarkedStudent(Protocol):
    @property
    def student_id(self) -> str: ...


class OccurrenceMarksQuery(Protocol):
    """Attendance already recorded for an occurrence (Coaching-owned; the
    composition root passes its attendance repository)."""

    async def list_for_occurrence(self, occurrence_id: str) -> Sequence[MarkedStudent]: ...


class TrialOutcomeQuery(Protocol):
    async def outcomes_for(self, request_ids: list[str]) -> dict[str, str | None]: ...


class GetOccurrenceRoster:
    def __init__(
        self,
        *,
        get_roster: GetSessionRoster,
        absence_notices: AbsenceNoticeQuery,
        occurrence_roster: OccurrenceRosterQuery,
        students: StudentQuery,
        occurrences: SessionOccurrenceRepository,
        trial_outcomes: TrialOutcomeQuery | None = None,
        marks: OccurrenceMarksQuery | None = None,
    ) -> None:
        self._marks = marks
        # Optional so hand-built fixtures that predate L3a keep working.
        self._trial_outcomes = trial_outcomes
        self._get_roster = get_roster
        self._absence_notices = absence_notices
        self._occurrence_roster = occurrence_roster
        # Same student query GetSessionRoster uses internally, so one-time
        # entries resolve full_name the same way regular roster entries do.
        self._students = students
        # Issue #694: one-time (makeup/trial) rows outlive their occurrence
        # when a session is deleted/regenerated or the date is cancelled —
        # the write-side cleanup can miss a path, so this read defensively
        # drops rows whose occurrence no longer exists or is cancelled.
        self._occurrences = occurrences

    async def execute(self, *, session_id: str, occurrence_id: str) -> list[OccurrenceRosterItem]:
        roster = await self._get_roster.execute(session_id)
        notices = await self._absence_notices.list_for_occurrence(occurrence_id)
        absent_student_ids = {n.student_id for n in notices}
        occurrence = await self._occurrences.get(occurrence_id)
        marked_ids = (
            {m.student_id for m in await self._marks.list_for_occurrence(occurrence_id)}
            if self._marks is not None
            else set()
        )
        if occurrence is not None:
            roster = [
                entry
                for entry in roster
                if entry.student_id in marked_ids
                or entry.enrolled_at is None
                or _aware(entry.enrolled_at) <= occurrence.end_at
            ]

        out: list[OccurrenceRosterItem] = [
            OccurrenceRosterItem(
                enrollment_id=entry.enrollment_id,
                student_id=entry.student_id,
                full_name=entry.full_name,
                status=entry.status,
                entry_source="enrollment",
                expected_absence=entry.student_id in absent_student_ids,
                pending_cancellation_at=entry.pending_cancellation_at,
                hold_return_on=entry.hold_return_on,
                age_years=entry.age_years,
            )
            for entry in roster
        ]

        one_time_entries = await self._occurrence_roster.list_for_occurrence(occurrence_id)
        if one_time_entries:
            # Issue #694: the occurrence may have been cancelled or dropped
            # entirely (session deleted/regenerated) after these rows were
            # written. A coach can never mark such a row (#676's
            # occurrence-status guard rejects the write), so don't render it.
            if occurrence is None or occurrence.status == "cancelled":
                one_time_entries = []
        if one_time_entries:
            students = await self._students.by_ids([e.student_id for e in one_time_entries])
            students_by_id = {s.student_id: s for s in students}
            trial_ids = [e.origin_request_id for e in one_time_entries if e.source == "trial"]
            outcomes: dict[str, str | None] = (
                await self._trial_outcomes.outcomes_for(trial_ids)
                if trial_ids and self._trial_outcomes is not None
                else {}
            )
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
                        trial_request_id=(
                            entry.origin_request_id if entry.source == "trial" else None
                        ),
                        trial_outcome=(
                            outcomes.get(entry.origin_request_id)
                            if entry.source == "trial"
                            else None
                        ),
                        age_years=age_in_years(
                            getattr(student, "date_of_birth", None), date.today()
                        ),
                    )
                )
        # A child marked for this class but no longer on the roster (withdrawn
        # since) keeps their row so the mark stays visible.
        listed = {row.student_id for row in out}
        departed = [sid for sid in marked_ids if sid not in listed]
        if departed:
            for student in await self._students.by_ids(sorted(departed)):
                out.append(
                    OccurrenceRosterItem(
                        enrollment_id=None,
                        student_id=student.student_id,
                        full_name=student.full_name,
                        status=None,
                        entry_source="enrollment",
                        expected_absence=student.student_id in absent_student_ids,
                    )
                )
        return out


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
