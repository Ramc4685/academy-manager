"""Coaching domain — attendance for Wave 1A.

Lesson plans and progress notes land in Wave 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AttendanceStatus = Literal["present", "absent", "late"]


class Attendance(BaseModel):
    """One mark for one student in one session."""

    model_config = {"frozen": True}

    attendance_id: str  # = mutation_id from the client (ULID)
    academy_id: str
    session_id: str
    student_id: str
    marked_by: str  # coach user_id
    marked_at: datetime
    marked_at_client: datetime | None = None
    status: AttendanceStatus
    client_app_version: str = Field(default="unknown")
