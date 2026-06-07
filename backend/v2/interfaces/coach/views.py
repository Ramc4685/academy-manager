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
    timezone: str | None = None
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


class RosterEntryView(BaseModel):
    enrollment_id: str
    student_id: str
    full_name: str
    enrollment_status: str


class RosterResponse(BaseModel):
    roster: list[RosterEntryView]


class AddStudentToRosterRequest(BaseModel):
    student_id: str
    parent_id: str
    full_name: str


class AddStudentToRosterResponse(BaseModel):
    enrollment_id: str
    session_id: str
    student_id: str
    status: str


class BulkAttendanceEntryRequest(BaseModel):
    student_id: str
    status: Literal["present", "absent", "late"]


class BulkMarkAttendanceRequest(BaseModel):
    mutation_id: str
    session_id: str
    entries: list[BulkAttendanceEntryRequest]


class BulkAttendanceEntryResponse(BaseModel):
    student_id: str
    status: Literal["present", "absent", "late"]
    attendance_id: str


class BulkMarkAttendanceResponse(BaseModel):
    results: list[BulkAttendanceEntryResponse]


class CreateFeedbackRequest(BaseModel):
    student_id: str
    occurrence_id: str | None = None
    body: str
    rating: int | None = None


class FeedbackView(BaseModel):
    feedback_id: str
    session_id: str
    occurrence_id: str | None = None
    coach_id: str
    student_id: str
    body: str
    rating: int | None = None
    created_at: datetime


class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackView]


# ---------------------------------------------------------------------------
# Billing enrollment views (Phase 2)
# ---------------------------------------------------------------------------


class CoachBillingEnrollmentView(BaseModel):
    enrollment_id: str
    student_id: str
    session_type_id: str
    session_type_name: str
    status: str
    billing_start_date: datetime
    override_price_cents: int | None = None


class ProrationPreviewView(BaseModel):
    credit_cents: int
    charge_cents: int
    net_cents: int
    from_session_type_id: str | None
    to_session_type_id: str


class MoveEnrollmentResponse(BaseModel):
    enrollment: CoachBillingEnrollmentView
    proration: ProrationPreviewView


# ---------------------------------------------------------------------------
# Schedule (all upcoming sessions for the coach)
# ---------------------------------------------------------------------------


class CoachScheduleEntry(BaseModel):
    session_id: str
    occurrence_id: str
    title: str
    location: str
    timezone: str | None = None
    start_at: datetime
    end_at: datetime


class CoachScheduleResponse(BaseModel):
    sessions: list[CoachScheduleEntry]


# ---------------------------------------------------------------------------
# Self-service profile
# ---------------------------------------------------------------------------


class CoachProfileResponse(BaseModel):
    user_id: str
    display_name: str
    email: str
    phone: str | None = None


class UpdateCoachProfileRequest(BaseModel):
    display_name: str | None = None
    phone: str | None = None
    email: str | None = None
