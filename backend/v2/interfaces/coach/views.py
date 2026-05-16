"""Coach BFF view DTOs (persona-shaped responses).

These are the *only* shape the coach client sees. Never includes payment,
payout, admin-only, or other-persona fields. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CoachRosterEntry(BaseModel):
    student_id: str
    full_name: str
    enrollment_status: Literal["active", "paused", "cancelled"]


class CoachSession(BaseModel):
    session_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    roster: list[CoachRosterEntry]


class CoachTodayResponse(BaseModel):
    date: str  # YYYY-MM-DD
    sessions: list[CoachSession]


class MarkAttendanceRequest(BaseModel):
    mutation_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at_client: datetime | None = None
    client_app_version: str = "unknown"


class MarkAttendanceResponse(BaseModel):
    attendance_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at: datetime
