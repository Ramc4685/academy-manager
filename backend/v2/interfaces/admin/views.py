"""Admin BFF view DTOs.

Admin-shaped — academy-wide read fields included. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


# --- Directory ---


class AdminUserView(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    role: Literal["admin", "coach", "parent"]
    status: str


class AdminUserList(BaseModel):
    users: list[AdminUserView]


class AdminStudentView(BaseModel):
    student_id: str
    full_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    status: str
    active_session_count: int
    last_seen_at: datetime | None = None
    attendance_rate: float | None = None
    dues_status: Literal["current", "due", "overdue"] = "current"


class AdminStudentList(BaseModel):
    students: list[AdminStudentView]
    next_cursor: str | None = None


# --- Sessions ---


class AdminSessionView(BaseModel):
    session_id: str
    coach_id: str
    coach_name: str | None = None
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int
    status: Literal["scheduled", "cancelled", "completed"]
    enrolled_count: int = 0
    waitlist_count: int = 0


class AdminSessionList(BaseModel):
    sessions: list[AdminSessionView]


class CreateSessionRequest(BaseModel):
    coach_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int


# --- Enrollments ---


class AdminEnrollmentView(BaseModel):
    enrollment_id: str
    session_id: str
    student_id: str
    student_name: str
    full_name: str
    parent_id: str
    status: str
    enrolled_at: datetime | None = None


class AdminEnrollmentList(BaseModel):
    enrollments: list[AdminEnrollmentView]


class EditRosterAddRequest(BaseModel):
    session_id: str
    student_id: str
    parent_id: str
    full_name: str


class TransferEnrollmentRequest(BaseModel):
    target_session_id: str


# --- Waitlist ---


class AdminWaitlistEntry(BaseModel):
    waitlist_id: str
    session_id: str
    student_id: str
    parent_id: str
    joined_at: datetime
    full_name: str = "(unknown)"
    position: int = 0
    added_at: datetime | None = None
    status: str


class AdminWaitlistList(BaseModel):
    entries: list[AdminWaitlistEntry]
    waitlist: list[AdminWaitlistEntry]


class AdminPauseRequestView(BaseModel):
    pause_request_id: str
    enrollment_id: str
    parent_id: str
    period: str
    reason: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class AdminPauseRequestList(BaseModel):
    requests: list[AdminPauseRequestView]


# --- Billing ---


class AdminPaymentView(BaseModel):
    payment_id: str
    parent_id: str
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    session_id: str | None
    period: str | None = None
    amount_cents: int
    discount_cents: int = 0
    final_amount_cents: int | None = None
    currency: str
    status: str
    refunded_cents: int
    invoice_number: str | None = None
    payment_method: str | None = None
    stripe_linked: bool = False
    created_at: datetime


class AdminPaymentList(BaseModel):
    payments: list[AdminPaymentView]


class IssueRefundRequest(BaseModel):
    payment_id: str
    amount_cents: int | None = None
    reason: str = "admin_initiated"


class GenerateMonthlyPaymentsRequest(BaseModel):
    period: str


class GenerateMonthlyPaymentsResponse(BaseModel):
    created: int
    skipped_existing: int = 0
    skipped_no_charge: int = 0
    skipped_autopay: int = 0
    skipped_paused: int = 0


class MarkPaymentPaidRequest(BaseModel):
    payment_method: str = "cash"
    notes: str = ""


class ApplyPaymentDiscountRequest(BaseModel):
    discount_cents: int


# --- Finance (# FINANCE) ---


class AdminPayoutView(BaseModel):  # FINANCE
    payout_id: str
    coach_id: str
    amount_cents: int
    period_start: datetime
    period_end: datetime
    paid_at: datetime | None


class AdminPayoutList(BaseModel):  # FINANCE
    payouts: list[AdminPayoutView]


class AdminExpenseView(BaseModel):  # FINANCE
    expense_id: str
    category: str
    amount_cents: int
    note: str
    incurred_on: datetime


class AdminExpenseList(BaseModel):  # FINANCE
    expenses: list[AdminExpenseView]


class RecordExpenseRequest(BaseModel):  # FINANCE
    category: Literal["rent", "equipment", "salary", "marketing", "other"]
    amount_cents: int
    note: str = ""
    incurred_on: datetime | None = None


class AdminRevenueResponse(BaseModel):  # FINANCE
    by_month: dict[str, int]


class AdminAuditLogView(BaseModel):
    audit_id: str
    actor_id: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    created_at: datetime


class AdminAuditLogList(BaseModel):
    logs: list[AdminAuditLogView]


class DuesFollowupParentView(BaseModel):
    parent_id: str
    parent_name: str | None = None
    email: str | None = None
    pending_count: int
    total_due_cents: int


class DuesFollowupResponse(BaseModel):
    parents: list[DuesFollowupParentView]


class SendDuesRemindersResponse(BaseModel):
    sent: int
    blocked: bool
    reason: str


# --- Comms ---


class AdminMessageView(BaseModel):
    message_id: str
    kind: str
    sender_id: str
    recipient_id: str | None
    body: str
    created_at: datetime


class AdminMessageList(BaseModel):
    messages: list[AdminMessageView]


AdminWaiverStatus = Literal["signed", "pending", "expiring", "outdated"]


class AdminWaiverSummaryView(BaseModel):
    signed_current: int
    pending_signature: int
    expiring_30d: int
    outdated_version: int
    active_students: int = 0
    adoption_rate: float | None = None


class AdminWaiverDocumentView(BaseModel):
    title: str
    version: str
    description: str | None = None
    effective_at: datetime | None = None
    last_edited_at: datetime | None = None
    signed_count: int | None = None
    total_count: int | None = None
    adoption_rate: float | None = None


class AdminWaiverStudentView(BaseModel):
    waiver_id: str
    student_id: str
    student_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    status: AdminWaiverStatus
    version: str | None = None
    signed_at: datetime | None = None
    method: str | None = None
    expires_at: datetime | None = None


class AdminWaiverList(BaseModel):
    summary: AdminWaiverSummaryView
    current_waiver: AdminWaiverDocumentView | None = None
    waivers: list[AdminWaiverStudentView] = []


class BroadcastRequest(BaseModel):
    body: str


class DMRequest(BaseModel):
    recipient_id: str
    body: str


# --- Settings ---


class AdminAcademyView(BaseModel):
    academy_id: str
    display_name: str
    timezone: str
    contact_email: str | None = None
    contact_phone: str | None = None
    hours_text: str | None = None
    address: str | None = None


class UpdateAdminAcademyRequest(BaseModel):
    display_name: str | None = None
    timezone: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    hours_text: str | None = None
    address: str | None = None


class AdminFeesView(BaseModel):
    default_monthly_cents: int | None = None
    late_fee_cents: int | None = None
    grace_days: int | None = None


class UpdateAdminFeesRequest(BaseModel):
    default_monthly_cents: int | None = None
    late_fee_cents: int | None = None
    grace_days: int | None = None


class AdminNotificationsView(BaseModel):
    dues_reminders: bool = False
    attendance_alerts: bool = False
    daily_digest_to_admin: bool = False


class UpdateAdminNotificationsRequest(BaseModel):
    dues_reminders: bool | None = None
    attendance_alerts: bool | None = None
    daily_digest_to_admin: bool | None = None


class AdminGatewayView(BaseModel):
    stripe_connected: bool
    stripe_account_id_masked: str | None = None
    manual_methods: list[str]


class UpdateAdminUserRoleRequest(BaseModel):
    role: Literal["admin", "coach", "parent"]
