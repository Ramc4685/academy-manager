"""Coach BFF view DTOs (persona-shaped responses).

These are the *only* shape the coach client sees. Never includes payment,
payout, admin-only, or other-persona fields. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    DailyTeachingPlan,
    LevelTeachingGroup,
    UnplacedStudent,
)
from backend.v2.contexts.coaching.application.use_cases.session_notes import NoteVisibility
from backend.v2.shared.comms import MAX_ANNOUNCEMENT_BODY

# Client-generated ULID (Crockford base32, 26 chars). Constrained because it is
# used as an idempotency-key component and becomes the attendance primary key —
# an unconstrained string would let clients submit arbitrary/oversized keys
# (#544).
MutationId = Annotated[str, Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]

# Today's teaching plan across all of the coach's sessions for a date
# (GET /api/v2/coach/today/plan). Shape is plan section 4.
CoachTeachingPlanResponse = DailyTeachingPlan


class CoachSessionTeachingPlanResponse(BaseModel):
    """Teaching plan for a single session (GET /sessions/{id}/teaching-plan)."""

    program_id: str = ""
    program_name: str = ""
    pathway_configured: bool = False
    session_id: str
    groups: list[LevelTeachingGroup] = []
    unplaced: list[UnplacedStudent] = []


class CoachRosterEntry(BaseModel):
    student_id: str
    full_name: str
    enrollment_status: Literal["active", "paused", "cancelled"] | None = None
    # Already-recorded mark for this occurrence, so the client can hydrate
    # attendance state after a reload instead of treating everyone as unmarked.
    attendance_status: Literal["present", "absent", "late"] | None = None
    # True when a parent submitted an AbsenceNotice (R1) for this student on
    # this occurrence.
    expected_absence: bool = False
    # "enrollment" for regular roster rows; "makeup" / "trial" for one-time
    # entries (Tasks 5/7) added just for this occurrence.
    entry_source: Literal["enrollment", "makeup", "trial"] = "enrollment"


class CoachSession(BaseModel):
    session_id: str
    occurrence_id: str
    title: str
    location: str
    timezone: str | None = None
    start_at: datetime
    end_at: datetime
    roster: list[CoachRosterEntry]
    # Primary coach of the session. ``coach_name`` is resolved only for coach
    # supervisors (admin/owner covering the academy-wide list); coaches see
    # their own id and a null name.
    coach_id: str | None = None
    coach_name: str | None = None


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
    mutation_id: MutationId
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


class CorrectAttendanceRequest(BaseModel):
    status: Literal["present", "absent", "late"]
    reason: str | None = None


class CorrectAttendanceResponse(BaseModel):
    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    status: Literal["present", "absent", "late"]
    previous_status: Literal["present", "absent", "late"] | None = None
    corrected_by: str | None = None
    corrected_at: datetime | None = None


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
    # "shared" = the student's parent sees it; "private" stays with coaches.
    visibility: NoteVisibility = "private"


class ProgressNoteList(BaseModel):
    notes: list[ProgressNoteView]


class CreateProgressNoteRequest(BaseModel):
    student_id: str
    body: str
    visibility: NoteVisibility = "private"


class SetNoteVisibilityRequest(BaseModel):
    """PATCH body for both progress notes and skill notes."""

    visibility: NoteVisibility


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
    mutation_id: MutationId
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
    coach_id: str | None = None
    coach_name: str | None = None


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


# ---------------------------------------------------------------------------
# Messages inbox (UIM13)
# ---------------------------------------------------------------------------


class CoachMessageView(BaseModel):
    message_id: str
    kind: Literal["dm", "announcement"]
    sender_persona: Literal["admin", "coach", "parent"]
    body: str
    created_at: datetime
    read: bool
    scope_label: str | None = None
    urgency: Literal["routine", "urgent"] = "routine"
    author_display_name: str | None = None


class CoachSessionAnnouncementPostRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_ANNOUNCEMENT_BODY)
    urgent: bool = False

    @field_validator("body")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("announcement body must not be blank")
        return stripped


class CoachSessionAnnouncementView(BaseModel):
    message_id: str
    session_id: str
    body: str
    urgency: Literal["routine", "urgent"]
    author_id: str
    author_display_name: str | None = None
    author_persona: Literal["admin", "coach", "parent"]
    created_at: datetime
    #: Whether THIS viewer may delete it. Computed server-side (admin: always;
    #: coach: only their own posts) so the client never has to re-derive an
    #: authorization rule the API is the authority on.
    can_delete: bool = False


class CoachSessionAnnouncementList(BaseModel):
    announcements: list[CoachSessionAnnouncementView]


class CoachSessionAnnouncementPostResponse(BaseModel):
    announcement: CoachSessionAnnouncementView
    email_status: Literal["skipped", "sent", "no_recipients", "failed"]
    sent_count: int = 0
    failed_count: int = 0


class CoachMessagesResponse(BaseModel):
    messages: list[CoachMessageView]


class CoachMarkMessageReadResponse(BaseModel):
    status: Literal["ok"] = "ok"
