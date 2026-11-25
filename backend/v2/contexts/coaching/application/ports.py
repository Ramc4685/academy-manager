"""Coaching application ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.coaching.domain.dropoff import DropoffCheckin
from backend.v2.contexts.coaching.domain.models import (
    Attendance,
    AttendanceEntrySource,
    AttendanceStatus,
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


# --- Admin attendance review (Inbox "Attendance" tab) ---


class ReviewOccurrence(BaseModel):
    """One past class date with its roster size and recorded marks (voided included)."""

    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    session_name: str
    start_at: datetime
    status: str
    enrolled_count: int
    marked_count: int


class ReviewCorrection(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    occurrence_id: str
    session_id: str
    session_name: str
    start_at: datetime | None
    student_id: str
    student_name: str
    status: AttendanceStatus
    previous_status: AttendanceStatus | None
    corrected_at: datetime
    corrected_by_name: str | None
    reason: str | None


class AttendanceReviewReader(Protocol):
    async def occurrences_between(self, start: datetime, end: datetime) -> list[ReviewOccurrence]:
        """Non-cancelled class dates starting in ``[start, end)``."""
        ...

    async def corrections_since(self, since: datetime) -> list[ReviewCorrection]: ...


class DropoffPolicy(BaseModel):
    """The academy's drop-off check-in switch and window (minutes)."""

    model_config = {"frozen": True}

    enabled: bool = False
    opens_minutes_before: int = 30
    closes_minutes_after: int = 15


class DropoffPolicyLookup(Protocol):
    """Reads the academy's self-service policy. Enrollment owns it, so the
    composition root adapts it into this shape (ADR-0005 rule 5)."""

    async def get(self) -> DropoffPolicy: ...


class GuardianLookup(Protocol):
    async def is_guardian(self, parent_id: str, student_id: str) -> bool:
        """True when this parent owns this student in the request tenant."""
        ...


class ExpectedRosterLookup(Protocol):
    async def expected_student_ids(
        self, *, occurrence_id: str, session_id: str, template_session_id: str | None
    ) -> list[str]:
        """Students expected at this occurrence: active enrollments in the
        session (or its template) plus one-time make-up / trial entries."""
        ...


class DropoffMarkReader(Protocol):
    """The attendance marks a check-in's displayed state is derived from."""

    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None: ...

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[Attendance]: ...


class DropoffCheckinRepository(Protocol):
    async def report(self, checkin: DropoffCheckin) -> DropoffCheckin:
        """Insert unless a row exists for (occurrence, student); return the
        stored row either way (a repeat tap returns the first report)."""
        ...

    async def get(self, occurrence_id: str, student_id: str) -> DropoffCheckin | None: ...

    async def begin_confirm(
        self, occurrence_id: str, student_id: str, *, confirm_mutation_id: str, staff_id: str
    ) -> DropoffCheckin | None:
        """Atomically move ``reported`` -> ``confirming``. Returns the row
        after the attempt (already confirming/confirmed rows come back
        unchanged), or None when there is no row."""
        ...

    async def finish_confirm(
        self,
        occurrence_id: str,
        student_id: str,
        *,
        attendance_id: str,
        reconciled: bool,
        confirmed_at: datetime,
        confirmed_by: str,
    ) -> DropoffCheckin | None:
        """Move ``confirming`` -> ``confirmed``; a no-op on any other status.
        Returns the row after the attempt."""
        ...

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[DropoffCheckin]: ...

    async def list_for_student(
        self, student_id: str, occurrence_ids: list[str]
    ) -> list[DropoffCheckin]: ...
