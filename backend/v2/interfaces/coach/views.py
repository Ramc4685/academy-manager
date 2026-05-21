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
    occurrence_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    roster: list[CoachRosterEntry]


class CoachTodayResponse(BaseModel):
    date: str  # YYYY-MM-DD
    sessions: list[CoachSession]


class CoachDashboardResponse(BaseModel):
    active_student_count: int
    sessions_today: int
    attendance_percentage: float
    expected_cut_cents: int
    marked_attendance_count: int


class MarkAttendanceRequest(BaseModel):
    mutation_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at_client: datetime | None = None
    client_app_version: str = "unknown"


class MarkAttendanceResponse(BaseModel):
    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    marked_at: datetime


class LessonPlanView(BaseModel):
    lesson_plan_id: str
    session_id: str
    coach_id: str
    title: str
    body: str
    created_at: datetime


class LessonPlanList(BaseModel):
    plans: list[LessonPlanView]


class CreateLessonPlanRequest(BaseModel):
    title: str
    body: str


class ProgressNoteView(BaseModel):
    note_id: str
    session_id: str
    student_id: str
    coach_id: str
    body: str
    created_at: datetime


class ProgressNoteList(BaseModel):
    notes: list[ProgressNoteView]


class CreateProgressNoteRequest(BaseModel):
    student_id: str
    body: str
