"""Coaching domain — attendance for Wave 1A.

Lesson plans and progress notes land in Wave 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AttendanceStatus = Literal["present", "absent", "late"]
CoachAttendanceStatus = Literal["present", "absent"]
CoachAttendanceRole = Literal["lead", "assistant"]
CoachAttendanceSource = Literal["coach_self", "admin"]


class Attendance(BaseModel):
    """One mark for one student in one dated session occurrence."""

    model_config = {"frozen": True}

    attendance_id: str  # = mutation_id from the client (ULID)
    academy_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    marked_by: str  # coach user_id
    marked_at: datetime
    marked_at_client: datetime | None = None
    status: AttendanceStatus
    client_app_version: str = Field(default="unknown")
    # Correction audit trail (#517) — set only when a coach/admin corrects a
    # previously recorded mark. `previous_status` is the status the last
    # correction replaced.
    corrected_by: str | None = None
    corrected_at: datetime | None = None
    previous_status: AttendanceStatus | None = None
    correction_reason: str | None = None


class CoachAttendance(BaseModel):
    """One payroll attendance mark for one coach in one occurrence."""

    model_config = {"frozen": True}

    attendance_id: str
    academy_id: str
    occurrence_id: str
    coach_id: str
    status: CoachAttendanceStatus
    role: CoachAttendanceRole = "lead"
    source: CoachAttendanceSource
    marked_by: str
    marked_at: datetime
    rate_override_minor: int | None = Field(default=None, ge=0)
    note: str = ""


class SessionFeedback(BaseModel):
    """One coach-authored feedback entry for a student in a session."""

    model_config = {"frozen": True}

    feedback_id: str  # ULID
    academy_id: str
    session_id: str
    occurrence_id: str | None = None
    coach_id: str
    student_id: str
    body: str
    rating: int | None = Field(default=None, ge=1, le=5)  # 1-5 if present
    created_at: datetime


class CoachSkillNote(BaseModel):
    """A coach's free-text note about a student's skill."""

    model_config = {"frozen": True}

    note_id: str
    academy_id: str
    student_id: str
    skill_id: str
    coach_id: str
    session_id: str | None = None
    body: str
    created_at: datetime
