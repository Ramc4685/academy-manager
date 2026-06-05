"""Coaching application ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.coaching.domain.models import (
    Attendance,
    CoachAttendance,
    SessionFeedback,
)


class AttendanceRepository(Protocol):
    async def save(self, attendance: Attendance) -> None: ...
    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None: ...
    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None: ...


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


class OccurrenceLookup(Protocol):
    async def get(self, occurrence_id: str) -> OccurrenceDetails | None: ...


class SessionLookup(Protocol):
    """Coaching reads sessions through this port — the implementation wraps
    the Enrollment SessionQuery, but Coaching never imports Enrollment
    directly (ADR-0005, rule 5).
    """

    async def is_coach_assigned(self, coach_id: str, session_id: str, on_date: date) -> bool: ...
    async def is_cancelled(self, session_id: str) -> bool: ...
    async def session_date(self, session_id: str) -> date | None: ...


class EnrollmentLookup(Protocol):
    async def is_active(self, session_id: str, student_id: str) -> bool: ...


class SkillNoteRepository(Protocol):
    async def save(self, note: object) -> None: ...
    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[object]: ...
