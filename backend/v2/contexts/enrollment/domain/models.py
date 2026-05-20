"""Enrollment domain — read-side slice for Wave 1A.

Aggregates: Session, Enrollment, Student. Write-side (create session, edit
roster, waitlist promotion) lands in Wave 2/3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EnrollmentStatus = Literal["active", "paused", "cancelled", "withdrawn"]
SessionStatus = Literal["scheduled", "cancelled", "completed"]


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
