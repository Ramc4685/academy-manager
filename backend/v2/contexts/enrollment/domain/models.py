"""Enrollment domain — read-side slice for Wave 1A.

Aggregates: Session, Enrollment, Student. Write-side (create session, edit
roster, waitlist promotion) lands in Wave 2/3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EnrollmentStatus = Literal["active", "paused", "cancelled", "withdrawn"]
SessionStatus = Literal["scheduled", "cancelled", "completed"]
SessionOccurrenceStatus = Literal["scheduled", "cancelled", "completed"]


class Session(BaseModel):
    """A scheduled training session.

    Per data-ownership.md, the Enrollment context is the sole writer for
    `sessions`. Coaching reads this aggregate for the today screen.
    """

    model_config = {"frozen": True}

    session_id: str
    academy_id: str
    coach_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int = Field(ge=1)
    status: SessionStatus = "scheduled"
    days_of_week: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None


class SessionOccurrence(BaseModel):
    """One dated occurrence produced from a recurring session template."""

    model_config = {"frozen": True}

    occurrence_id: str
    academy_id: str
    session_id: str
    start_at: datetime
    end_at: datetime
    status: SessionOccurrenceStatus = "scheduled"
    scheduled_coach_id: str
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    is_billable: bool = True
    is_payable: bool = True
    cancellation_reason: str | None = None
    template_session_id: str | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> SessionOccurrence:
        if self.end_at <= self.start_at:
            raise ValueError("session occurrence end_at must be after start_at")
        return self


class Student(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    academy_id: str
    parent_id: str
    full_name: str


class Enrollment(BaseModel):
    """A student's enrollment in a session."""

    model_config = {"frozen": True}

    enrollment_id: str
    academy_id: str
    session_id: str
    student_id: str
    status: EnrollmentStatus = "active"


class RosterEntry(BaseModel):
    """Pair of (enrollment, student) joined for roster display."""

    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str
    full_name: str
    status: EnrollmentStatus
