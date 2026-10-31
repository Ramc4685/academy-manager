"""Coaching application ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.coaching.domain.models import (
    Attendance,
    AttendanceEntrySource,
    CoachAttendance,
    CoachAttendanceAuditEntry,
    CoachSkillNote,
    NoteVisibility,
    SessionFeedback,
)


class AttendanceRepository(Protocol):
    async def save(self, attendance: Attendance) -> None: ...
    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None: ...
    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None: ...
    async def update_status(self, attendance: Attendance) -> None: ...


class SessionFeedbackRepository(Protocol):
    async def save(self, feedback: SessionFeedback) -> None: ...
    async def list_for_session(
        self, session_id: str, *, limit: int = 100
    ) -> list[SessionFeedback]: ...
    async def list_for_student(
        self, student_id: str, *, limit: int = 100
    ) -> list[SessionFeedback]: ...


class CoachAttendanceRepository(Protocol):
    async def upsert(self, row: CoachAttendance) -> CoachAttendance: ...
    async def find_for_occurrence_coach(
        self, occurrence_id: str, coach_id: str
    ) -> CoachAttendance | None: ...
    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[CoachAttendance]: ...


class CoachAttendanceAuditRepository(Protocol):
    async def append(self, entry: CoachAttendanceAuditEntry) -> None: ...


class OccurrenceDetails(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    starts_at: datetime
    status: str
    scheduled_coach_id: str
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    template_session_id: str | None = None
    # Assistant coaches listed on the occurrence: allowed to mark attendance
    # like an assigned coach. Not a payroll field.
    assistant_coach_ids: tuple[str, ...] = ()


class OccurrenceLookup(Protocol):
    async def get(self, occurrence_id: str) -> OccurrenceDetails | None: ...


class PayoutPeriodLock(Protocol):
    """Is this coach's payroll for this instant already frozen? (#787)

    Finance owns ``PayoutPeriod``; Coaching must not import it (ADR-0005
    rule 5), so the composition layer reshapes it into this one question.
    Returns the blocking period's status (``"approved"`` / ``"paid"``), or
    ``None`` when the window is still editable.
    """

    async def locked_status_for(self, *, coach_id: str, at: datetime) -> str | None: ...


class SessionLookup(Protocol):
    """Coaching reads sessions through this port — the implementation wraps
    the Enrollment SessionQuery, but Coaching never imports Enrollment
    directly (ADR-0005, rule 5).
    """

    async def is_coach_assigned(self, coach_id: str, session_id: str, on_date: date) -> bool: ...
    async def is_cancelled(self, session_id: str) -> bool: ...
    async def session_date(self, session_id: str) -> date | None: ...


class AttendanceEligibility(BaseModel):
    """Why a student may be marked on one occurrence (issue #672)."""

    model_config = {"frozen": True}

    source: AttendanceEntrySource


class EnrollmentLookup(Protocol):
    async def is_active(self, session_id: str, student_id: str) -> bool: ...

    async def attendance_eligibility(
        self,
        *,
        occurrence_id: str,
        session_id: str,
        template_session_id: str | None,
        student_id: str,
    ) -> AttendanceEligibility | None:
        """Occurrence-aware eligibility: an ``active`` enrollment in the
        session (or its recurring template), or an approved one-time
        make-up / trial roster entry for exactly this occurrence. ``None``
        when the student may not be marked — paused, cancelled and
        withdrawn enrollments stay ineligible."""
        ...


class SkillNoteRepository(Protocol):
    async def save(self, note: CoachSkillNote) -> None: ...

    async def list_for_student_skill(
        self, student_id: str, skill_id: str
    ) -> list[CoachSkillNote]: ...

    async def get(self, student_id: str, note_id: str) -> CoachSkillNote | None: ...

    async def set_visibility(
        self, student_id: str, note_id: str, visibility: NoteVisibility
    ) -> CoachSkillNote | None: ...
