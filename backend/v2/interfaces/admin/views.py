"""Admin BFF view DTOs.

Admin-shaped — academy-wide read fields included. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

# --- Directory ---


class AdminUserView(BaseModel):
    user_id: str
    email: EmailStr
    display_name: str
    role: Literal["admin", "coach", "parent"]
    status: str


class AdminUserDetailView(AdminUserView):
    phone: str | None = None
    roles: list[Literal["admin", "coach", "parent"]] = []
    linked_student_count: int = 0
    session_count: int = 0


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


class AdminStudentSessionSummaryView(BaseModel):
    enrollment_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: str
    payment_mode: str | None = None
    subscription_status: str | None = None
    amount_cents: int | None = None


class AdminStudentPaymentSummaryView(BaseModel):
    payment_id: str
    session_id: str | None = None
    period: str | None = None
    amount_cents: int
    paid_amount_cents: int
    balance_due_cents: int
    status: str
    payment_method: str | None = None
    invoice_number: str | None = None
    paid_at: datetime | None = None
    stripe_invoice_id: str | None = None
    stripe_payment_intent_id: str | None = None
    created_at: datetime


class AdminStudentCurrentPaymentSummaryView(BaseModel):
    amount_cents: int
    source: Literal["invoice"]
    status: str
    period: str | None = None
    payment_id: str | None = None
    session_id: str | None = None
    session_title: str | None = None


class AdminStudentRecentAttendanceView(BaseModel):
    session_id: str | None = None
    date: str | None = None
    status: str
    marked_at: datetime | None = None


class AdminStudentDetailView(AdminStudentView):
    date_of_birth: date | None = None
    level: str | None = None
    notes: str | None = None
    parent_phone: str | None = None
    parent_details: str | None = None
    previous_experience: str | None = None
    medical_notes: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    t_shirt_size: str | None = None
    waiver_status: Literal["signed", "missing", "unknown"] = "unknown"
    waiver_signed_at: datetime | None = None
    waiver_version: str | None = None
    recent_attendance: list[AdminStudentRecentAttendanceView] = Field(default_factory=list)
    enrolled_sessions: list[AdminStudentSessionSummaryView] = Field(default_factory=list)
    payment_history: list[AdminStudentPaymentSummaryView] = Field(default_factory=list)
    current_payment: AdminStudentCurrentPaymentSummaryView | None = None
    outstanding_balance_cents: int = 0


class AdminStudentList(BaseModel):
    students: list[AdminStudentView]
    next_cursor: str | None = None


class UpdateAdminStudentRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    date_of_birth: date | None = None
    status: str | None = Field(default=None, max_length=32)
    parent_id: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    previous_experience: str | None = Field(default=None, max_length=1000)
    medical_notes: str | None = Field(default=None, max_length=1000)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=40)
    t_shirt_size: str | None = Field(default=None, max_length=20)
    reason: str = Field(default="admin profile update", min_length=1, max_length=500)


class ChangeAdminStudentParentRequest(BaseModel):
    parent_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500)


class AdminStudentParentSummaryView(BaseModel):
    parent_id: str
    display_name: str
    email: EmailStr
    phone: str | None = None


class AdminStudentParentChangeView(BaseModel):
    student_id: str
    parent: AdminStudentParentSummaryView
    previous_parent_id: str | None = None
    warnings: list[str] = []
    impact_counts: dict[str, int] = {}


class UpdateAdminUserRequest(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=32)
    reason: str = Field(default="admin user update", min_length=1, max_length=500)


class UpdateAdminUserRoleRequest(BaseModel):
    role: Literal["admin", "coach", "parent"]
    reason: str = Field(default="admin role change", min_length=1, max_length=500)


class CreateAdminUserRequest(BaseModel):
    role: Literal["admin", "coach", "parent"]
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=1, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    reason: str = Field(default="manual user creation", min_length=1, max_length=500)


class BulkInviteItem(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)


class BulkInviteRequest(BaseModel):
    users: list[BulkInviteItem] = Field(min_length=1, max_length=100)
    reason: str = Field(default="bulk parent invite", min_length=1, max_length=500)


class BulkInviteResultItem(BaseModel):
    email: str
    status: Literal["created", "skipped", "failed"]
    user_id: str | None = None
    detail: str | None = None


class BulkInviteResponse(BaseModel):
    created: int
    skipped: int
    failed: int
    results: list[BulkInviteResultItem]


# --- Session Type Billing ---


class SessionTypeView(BaseModel):
    session_type_id: str
    name: str
    description: str | None = None
    price_cents: int
    billing_period: Literal["monthly", "per_session"]
    overage_rate_cents: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SessionTypeList(BaseModel):
    session_types: list[SessionTypeView]


class CreateSessionTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_cents: int = Field(ge=0)
    billing_period: Literal["monthly", "per_session"] = "monthly"
    overage_rate_cents: int | None = Field(default=None, ge=0)


class UpdateSessionTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    price_cents: int | None = Field(default=None, ge=0)
    billing_period: Literal["monthly", "per_session"] | None = None
    overage_rate_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class StudentBillingEnrollmentView(BaseModel):
    enrollment_id: str
    student_id: str
    parent_id: str
    session_type_id: str
    stripe_subscription_id: str | None = None
    billing_start_date: datetime
    status: Literal["active", "paused", "cancelled", "transferred_out"]
    override_price_cents: int | None = None
    enrolled_at: datetime
    updated_at: datetime


class StudentBillingEnrollmentList(BaseModel):
    enrollments: list[StudentBillingEnrollmentView]


class MoveBillingEnrollmentRequest(BaseModel):
    to_session_type_id: str = Field(min_length=1)
    move_date: datetime
    period_start: datetime
    period_end: datetime
    reason: str | None = Field(default=None, max_length=500)


class SessionTypeProrationView(BaseModel):
    credit_cents: int
    charge_cents: int
    net_cents: int
    remaining_days: int
    total_days: int
    proration_ratio: str
    from_session_type_id: str | None
    to_session_type_id: str
    policy_version: str


class MoveBillingEnrollmentResponse(BaseModel):
    enrollment: StudentBillingEnrollmentView
    proration: SessionTypeProrationView
    stripe_invoice_id: str | None = None


class OverrideStudentPriceRequest(BaseModel):
    override_price_cents: int | None = Field(default=None, ge=0)


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
    amount_cents: int | None = None
    status: Literal["scheduled", "cancelled", "completed"]
    enrolled_count: int = 0
    waitlist_count: int = 0
    days_of_week: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None


class AdminSessionList(BaseModel):
    sessions: list[AdminSessionView]


class AdminCoachAttendanceView(BaseModel):
    attendance_id: str
    occurrence_id: str
    coach_id: str
    status: Literal["present", "absent"]
    role: Literal["lead", "assistant"]
    source: Literal["coach_self", "admin"]
    marked_by: str
    marked_at: datetime
    rate_override_minor: int | None = None
    note: str = ""


class AdminSessionOccurrenceView(BaseModel):
    occurrence_id: str
    session_id: str
    start_at: datetime
    end_at: datetime
    status: Literal["scheduled", "cancelled", "completed"]
    scheduled_coach_id: str
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    attendance_marked_count: int = 0
    attendance_marked_by: list[str] = Field(default_factory=list)
    attendance_last_marked_at: datetime | None = None
    coach_attendance: list[AdminCoachAttendanceView] = Field(default_factory=list)


class AdminSessionOccurrenceList(BaseModel):
    occurrences: list[AdminSessionOccurrenceView]


class UpdateSessionOccurrenceCoachRequest(BaseModel):
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    reason: str


class UpdateOccurrenceCoachAttendanceRequest(BaseModel):
    coach_id: str
    status: Literal["present", "absent"]
    role: Literal["lead", "assistant"] = "lead"
    rate_override_minor: int | None = Field(default=None, ge=0)
    note: str = ""


class CreateSessionRequest(BaseModel):
    coach_id: str
    title: str
    location: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    capacity: int
    amount_cents: int | None = Field(default=None, ge=0)
    days_of_week: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None


class EditSessionRequest(BaseModel):
    coach_id: str | None = None
    title: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1)
    amount_cents: int | None = Field(default=None, ge=0)
    days_of_week: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    reason: str | None = None


class UpdateOccurrenceReplacementRequest(BaseModel):
    replacement_coach_id: str | None = None
    reason: str | None = None


class AddSessionReplacementRequest(BaseModel):
    date: date
    replacement_coach_id: str
    reason: str | None = None


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
    level: str | None = None
    pathway_program_id: str | None = None
    pathway_level_id: str | None = None
    pathway_level_sequence: int | None = None
    pathway_level_name: str | None = None
    pathway_placement_status: str = "unplaced"
    pathway_skills_total: int = 0
    pathway_skills_completed: int = 0
    pathway_skills_ready_for_test: int = 0
    pathway_completion_percentage: int = 0
    pathway_next_action: str = "place_in_level"
    dues_status: Literal["current", "due", "overdue"] = "current"


class AdminEnrollmentList(BaseModel):
    enrollments: list[AdminEnrollmentView]


class EditRosterAddRequest(BaseModel):
    session_id: str
    student_id: str
    parent_id: str
    full_name: str


class TransferEnrollmentRequest(BaseModel):
    target_session_id: str
    effective_date: date
    reason: str | None = None


class OverrideEnrollmentFeeRequest(BaseModel):
    amount_cents: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=500)


class PauseEnrollmentRequest(BaseModel):
    effective_date: date
    reason: str | None = None


class WithdrawEnrollmentRequest(BaseModel):
    effective_date: date
    outcome: Literal["credit", "refund", "adjustment"] = "credit"
    reason: str = Field(min_length=1, max_length=500)


class RemoveEnrollmentRequest(BaseModel):
    effective_date: date
    reason: str = Field(min_length=1, max_length=500)


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


class AdminGlobalWaitlistSessionView(BaseModel):
    session_id: str
    title: str
    location: str
    start_at: datetime
    capacity: int
    enrolled_count: int = 0
    waitlist_count: int = 0
    entries: list[AdminWaitlistEntry]


class AdminGlobalWaitlistList(BaseModel):
    total_waitlisted: int
    sessions: list[AdminGlobalWaitlistSessionView]


class AdminPauseRequestView(BaseModel):
    pause_request_id: str
    enrollment_id: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    session_id: str | None = None
    session_title: str | None = None
    session_location: str | None = None
    session_start_at: datetime | None = None
    session_end_at: datetime | None = None
    period: str
    pause_kind: str = "fixed"
    resume_on: date | None = None
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
    invoice_id: str | None = None
    parent_id: str
    parent_name: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    session_id: str | None
    period: str | None = None
    amount_cents: int
    discount_cents: int = 0
    final_amount_cents: int | None = None
    amount_received_cents: int = 0
    paid_amount_cents: int = 0
    balance_due_cents: int | None = None
    overpayment_credit_cents: int = 0
    currency: str
    status: str
    refunded_cents: int
    invoice_number: str | None = None
    payment_method: str | None = None
    stripe_linked: bool = False
    stripe_customer_id: str | None = None
    stripe_checkout_session_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_invoice_id: str | None = None
    stripe_payment_intent_id: str | None = None
    reconciliation_status: str | None = None
    created_at: datetime


class AdminPaymentList(BaseModel):
    payments: list[AdminPaymentView]


class IssueRefundRequest(BaseModel):
    payment_id: str
    amount_cents: int | None = None
    reason: str = "admin_initiated"


class GenerateMonthlyPaymentsRequest(BaseModel):
    period: str | None = None
    month: str | None = Field(default=None, description="Deprecated alias for 'period'")

    @model_validator(mode="after")
    def _coerce_period(self) -> GenerateMonthlyPaymentsRequest:
        if self.period is None:
            if self.month is None:
                raise ValueError("'period' (or deprecated alias 'month') is required")
            self.period = self.month
        return self


class GenerateMonthlyPaymentsResponse(BaseModel):
    created: int
    skipped_existing: int = 0
    skipped_no_charge: int = 0
    skipped_autopay: int = 0
    skipped_paused: int = 0


class MarkPaymentPaidRequest(BaseModel):
    payment_method: Literal["cash", "check", "zelle", "venmo", "bank_transfer", "other"] = "cash"
    amount_received_cents: int | None = Field(default=None, gt=0)
    reference_number: str | None = None
    notes: str = ""
    payment_date: date | None = None


class ReconcileStripeBillingRequest(BaseModel):
    parent_id: str
    enrollment_id: str
    stripe_customer_id: str | None = None
    stripe_checkout_session_id: str
    reason: str = Field(min_length=8)


class ReconcileStripeBillingResponse(BaseModel):
    ok: bool
    mismatch_state: str | None = None
    payment_id: str | None = None
    stripe_customer_id: str | None = None
    stripe_checkout_session_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_invoice_id: str | None = None
    stripe_payment_intent_id: str | None = None
    audit_id: str


class BillingReconciliationMismatchView(BaseModel):
    code: str
    message: str
    stripe_value: Any | None = None
    local_value: Any | None = None


class BillingReconciliationReportResponse(BaseModel):
    result: str
    stripe_invoice_id: str | None = None
    payment_intent_id: str | None = None
    stripe_customer_id: str | None = None
    local_invoice_id: str | None = None
    ledger_payment_id: str | None = None
    payment_allocation_id: str | None = None
    mismatches: list[BillingReconciliationMismatchView] = Field(default_factory=list)
    checked_at: datetime


class BillingWebhookEventView(BaseModel):
    event_id: str
    event_type: str
    status: Literal["received", "processing", "processed", "failed", "quarantined"] | str
    object_id: str | None = None
    object_type: str | None = None
    received_at: datetime | None = None
    last_attempt_at: datetime | None = None
    retry_count: int = 0
    error_message: str | None = None


class BillingWebhookQueueResponse(BaseModel):
    events: list[BillingWebhookEventView]


class ApplyPaymentDiscountRequest(BaseModel):
    discount_cents: int
    reason: str = Field(min_length=1)


class AdminEnrollmentQuoteRequest(BaseModel):
    student_id: str | None = None
    session_id: str
    start_date: str | None = None


class AdminEnrollmentQuoteResponse(BaseModel):
    snapshot_id: str
    quote_expires_at: datetime | None = None
    amount_due_cents: int
    monthly_price_cents: int
    billing_period: str
    total_eligible_classes_this_month: int
    billable_remaining_classes_this_month: int
    formula: str
    included_occurrence_ids: list[str]
    excluded_occurrences: dict[str, str]
    policy_version: str
    settings_version: str
    schedule_signature: str | None = None


class WithdrawalCreditPreviewRequest(BaseModel):
    withdrawal_date: datetime


class WithdrawalCreditPreviewResponse(BaseModel):
    credit_amount_cents: int
    display_amount: str
    total_classes: int
    unused_classes: int
    formula: str
    message: str
    no_credit_reason: str | None = None


class WithdrawalCreditApproveRequest(BaseModel):
    withdrawal_date: datetime
    admin_note: str = ""
    cancel_subscription_immediately: bool = False


class WithdrawalCreditApproveResponse(BaseModel):
    status: str
    credit_amount_cents: int
    credit_balance_cents: int


# --- Invoices ---


class InvoiceLineDto(BaseModel):
    line_id: str | None = None
    invoice_id: str | None = None
    line_type: str | None = None
    description: str
    quantity: int | None = None
    unit_amount_cents: int | None = None
    amount_cents: int
    line_type: str | None = None
    quantity: int | None = None
    unit_amount_cents: int | None = None
    source_type: str | None = None
    source_id: str | None = None


class InvoiceDto(BaseModel):
    invoice_number: str = ""
    period: str
    lines: list[InvoiceLineDto] = []
    total_cents: int = 0
    paid_cents: int = 0
    balance_cents: int = 0
    status: str = "open"


class InvoicesResponse(BaseModel):
    invoices: list[InvoiceDto]


class InvoiceAllocationDto(BaseModel):
    payment_id: str
    amount_cents: int


class InvoiceCreditUsageDto(BaseModel):
    credit_id: str
    amount_cents: int


class InvoiceDetailResponse(BaseModel):
    invoice_id: str | None = None
    invoice_number: str
    period: str
    lines: list[InvoiceLineDto]
    subtotal_cents: int | None = None
    discount_cents: int | None = None
    total_cents: int | None = None
    balance_due_cents: int | None = None
    due_amount_cents: int
    paid_amount_cents: int
    status: str
    allocations: list[InvoiceAllocationDto] = []
    credit_usage: list[InvoiceCreditUsageDto] = []
    invoice_pdf_artifact_id: str | None = None
    receipt_artifact_id: str | None = None
    # delivery axis (separate from financial status)
    delivery_status: str = "not_sent"
    sent_at: datetime | None = None
    last_sent_at: datetime | None = None


class SendInvoiceResponse(BaseModel):
    invoice_id: str
    delivery_status: str
    sent_at: datetime | None = None
    last_sent_at: datetime | None = None
    checkout_url: str | None = None


class ChargeAutopayResponse(BaseModel):
    invoice_id: str
    success: bool
    status: str
    balance_due_cents: int
    requires_action: bool = False
    decline_code: str | None = None


class GenerateInvoiceArtifactRequest(BaseModel):
    artifact_type: Literal["invoice_pdf", "receipt"]


class GenerateInvoiceArtifactResponse(BaseModel):
    artifact_id: str
    artifact_type: Literal["invoice_pdf", "receipt"]
    status: Literal["generated"]


# --- Finance (# FINANCE) ---


class AdminPayoutView(BaseModel):  # FINANCE
    payout_id: str
    coach_id: str
    amount_cents: int
    period_start: datetime
    period_end: datetime
    paid_at: datetime | None
    expected_revenue_cents: int | None = None
    students_count: int | None = None
    sessions_count: int | None = None
    rule_label: str | None = None


class AdminPayoutList(BaseModel):  # FINANCE
    payouts: list[AdminPayoutView]


class GeneratePayoutPeriodRequest(BaseModel):
    coach_id: str
    period_start: datetime
    period_end: datetime


class MarkPayoutPeriodPaidRequest(BaseModel):
    method: Literal["bank_transfer", "cash", "check", "other"]
    paid_at: datetime
    amount_cents: int = Field(ge=0)
    reference: str | None = None


class AdminPayoutPeriodLineView(BaseModel):
    occurrence_id: str
    coach_id: str
    basis: Literal["scheduled", "substitute", "actual"]
    minutes: str
    amount_cents: int
    currency: str
    rate_id: str
    percent_bps: int | None = None
    expected_revenue_cents: int | None = None
    original_amount_cents: int | None = None
    adjustment_reason: str | None = None
    occurred_at: datetime | None = None
    session_title: str | None = None


class AdminUnpaidOccurrenceView(BaseModel):
    """An occurrence in the window that produced no pay line.

    Covers coach-marked-absent occurrences and occurrences whose pay
    could not be computed (e.g. session price missing for a percent
    rate). Rendered alongside the paid lines so the period reads as a
    complete session log.
    """

    occurrence_id: str
    occurred_at: datetime | None = None
    session_title: str | None = None


class AdminPayoutPeriodView(BaseModel):
    period_id: str
    coach_id: str
    period_start: datetime
    period_end: datetime
    status: Literal["draft", "approved", "paid"]
    currency: str
    total_amount_cents: int
    lines: list[AdminPayoutPeriodLineView]
    unpaid_occurrence_ids: list[str]
    unpaid_occurrences: list[AdminUnpaidOccurrenceView] = Field(default_factory=list)
    generated_at: datetime
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    paid_method: str | None = None
    paid_amount_cents: int | None = None
    paid_reference: str | None = None


class AdminPayoutPayslipView(BaseModel):
    printable: bool = True
    period: AdminPayoutPeriodView
    lines: list[AdminPayoutPeriodLineView]


class AdminMonthlyPayrollRow(BaseModel):
    coach_id: str
    coach_name: str | None = None
    session_count: int
    total_amount_cents: int
    currency: str
    status: str  # not_generated|draft|approved|paid
    period_id: str | None = None


class AdminMonthlyPayrollView(BaseModel):
    month: str
    period_start: datetime
    period_end: datetime
    rows: list[AdminMonthlyPayrollRow]
    total_amount_cents: int


class BulkPayrollResultView(BaseModel):
    month: str
    generated: int = 0
    skipped: int = 0
    recomputed: int = 0


class ReopenPayoutPeriodRequest(BaseModel):
    reason: str = Field(min_length=1)


class OverridePayoutLineRequest(BaseModel):
    amount_cents: int | None = Field(default=None, ge=0)
    """New amount for the line; ``None`` clears an existing override."""
    reason: str = Field(min_length=1)


class PayoutAuditEntryView(BaseModel):
    audit_id: str
    period_id: str
    occurrence_id: str | None = None
    action: Literal[
        "generated",
        "recomputed",
        "reopened",
        "approved",
        "marked_paid",
        "line_overridden",
        "line_override_cleared",
    ]
    actor_id: str
    at: datetime
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class PayoutAuditTrailView(BaseModel):
    entries: list[PayoutAuditEntryView]


class AdminCoachPayRateView(BaseModel):
    rate_id: str
    coach_id: str
    billing_unit: Literal["per_session", "per_hour", "percent_of_revenue"]
    amount_cents: int
    percent: float | None = None
    currency: str
    effective_from: datetime
    effective_until: datetime | None = None
    status: Literal["active", "superseded"]


class AdminCoachPayRateList(BaseModel):
    rates: list[AdminCoachPayRateView]


class SetCoachPayRateRequest(BaseModel):
    billing_unit: Literal["per_session", "per_hour", "percent_of_revenue"]
    amount_cents: int = Field(default=0, ge=0)
    percent: float | None = Field(default=None, ge=0, le=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    effective_from: datetime | None = None


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


class EditExpenseRequest(BaseModel):  # FINANCE
    category: Literal["rent", "equipment", "salary", "marketing", "other"] | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    note: str | None = None
    incurred_on: datetime | None = None
    reason: str | None = None


class DeleteExpenseRequest(BaseModel):  # FINANCE
    reason: str


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
    reason: str | None
    selected_parent_ids: list[str] = []
    generated_invoice_artifacts: int = 0


class SendDuesRemindersRequest(BaseModel):
    parent_ids: list[str] | None = None


# --- Comms ---


class AdminMessageView(BaseModel):
    message_id: str
    kind: str
    sender_id: str
    recipient_id: str | None
    body: str
    created_at: datetime
    sent_at: datetime
    is_broadcast: bool
    scope_type: str | None = None
    scope_label: str | None = None
    recipient_count: int | None = None
    delivery_status: str | None = None


class AdminMessageList(BaseModel):
    messages: list[AdminMessageView]


AdminWaiverStatus = Literal["signed", "pending", "expiring", "outdated"]
AdminWaiverTemplateStatus = Literal["draft", "active", "superseded", "retired"]


class AdminWaiverSummaryView(BaseModel):
    signed_current: int
    pending_signature: int
    expiring_30d: int
    outdated_version: int
    active_students: int = 0
    adoption_rate: float | None = None


class AdminWaiverDocumentView(BaseModel):
    waiver_id: str
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
    signature_id: str | None = None
    student_id: str
    student_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    status: AdminWaiverStatus
    template_id: str | None = None
    version: str | None = None
    signed_at: datetime | None = None
    method: str | None = None
    expires_at: datetime | None = None
    artifact_status: str = "unavailable"
    share_status: str = "unavailable"


class AdminWaiverList(BaseModel):
    summary: AdminWaiverSummaryView
    current_waiver: AdminWaiverDocumentView | None = None
    waivers: list[AdminWaiverStudentView] = []


class AdminWaiverTemplateCreateRequest(BaseModel):
    title: str
    body: str | None = None
    content: str | None = None


class AdminWaiverTemplateManagementView(BaseModel):
    waiver_template_id: str
    title: str
    body: str
    status: AdminWaiverTemplateStatus
    version: str | None = None
    content_hash: str | None = None
    effective_at: datetime | None = None
    published_at: datetime | None = None
    assigned_to_registration: bool = False
    assigned_at: datetime | None = None
    updated_at: datetime


class AdminWaiverTemplateManagementList(BaseModel):
    templates: list[AdminWaiverTemplateManagementView] = []


class AdminWaiverTemplateDetailView(BaseModel):
    waiver_id: str
    title: str
    version: str
    body: str | None = None
    content_hash: str | None = None
    effective_at: datetime | None = None
    artifact_status: str
    share_status: str
    gap_note: str


class AdminRegistrationRowView(BaseModel):
    application_id: str
    status: str
    parent_email: str
    parent_name: str | None = None
    student_name: str | None = None
    selected_session_id: str | None = None
    waiver_required: bool = False
    waiver_satisfied: bool = False
    updated_at: datetime


class AdminRegistrationListView(BaseModel):
    registrations: list[AdminRegistrationRowView] = []


class AdminRegistrationDetailView(AdminRegistrationRowView):
    parent_user_id: str
    child_first_name: str = ""
    child_last_name: str = ""
    child_skill_level: str = ""
    payment_id: str | None = None
    student_id: str | None = None
    enrollment_id: str | None = None
    waitlist_id: str | None = None
    session_title: str | None = None
    session_capacity: int | None = None
    waiver_template_id: str | None = None
    waiver_title: str | None = None
    waiver_version: str | None = None


class AdminRegistrationApproveRequest(BaseModel):
    session_id: str | None = None
    waiver_override_reason: str | None = None


class AdminRegistrationWaitlistRequest(BaseModel):
    session_id: str | None = None
    reason: str | None = None


class AdminRegistrationRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class AdminWaiverSignatureDetailView(BaseModel):
    signature_id: str
    student_name: str
    parent_name: str | None = None
    parent_email: str | None = None
    signed_at: datetime
    signer_name: str | None = None
    signer_email: str | None = None
    waiver_title: str | None = None
    waiver_version: str | None = None
    template_reference: str | None = None
    content_hash: str | None = None
    artifact_status: str
    share_status: str
    gap_note: str


AdminAttentionSeverity = Literal["high", "medium", "low"]
AdminAttentionKind = Literal[
    "overdue_dues",
    "pause_requests",
    "scheduled_resume_blocked",
    "waivers",
    "session_pressure",
]


class AdminAttentionItemView(BaseModel):
    attention_id: str
    kind: AdminAttentionKind
    title: str
    detail: str
    severity: AdminAttentionSeverity
    href: str
    count: int = 1


class AdminAttentionList(BaseModel):
    items: list[AdminAttentionItemView]


class BroadcastRequest(BaseModel):
    body: str
    scope_type: str = "academy"
    scope_label: str | None = None


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
    logo_url: str | None = None
    brand_color: str | None = None
    currency: str = "USD"


class UpdateAdminAcademyRequest(BaseModel):
    display_name: str | None = None
    timezone: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    hours_text: str | None = None
    address: str | None = None
    logo_url: str | None = None
    brand_color: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)


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
    coach_digest_enabled: bool = False
    coach_digest_hour: int = 6


class UpdateAdminNotificationsRequest(BaseModel):
    dues_reminders: bool | None = None
    attendance_alerts: bool | None = None
    daily_digest_to_admin: bool | None = None
    coach_digest_enabled: bool | None = None
    coach_digest_hour: int | None = Field(default=None, ge=0, le=23)


class CoachDigestTestSendRequest(BaseModel):
    # Target a specific coach by user_id, or omit/"self" to send to the admin.
    coach_id: str | None = None
    # Date to build the teaching-plan digest for. Omitted uses scheduler-local today.
    on_date: date | None = None


class CoachDigestTestSendResponse(BaseModel):
    status: Literal["sent", "skipped_empty", "failed"]
    coach_id: str
    email: str | None = None
    detail: str | None = None


class CoachDigestLogEntryView(BaseModel):
    digest_id: str
    coach_id: str
    coach_email: str | None = None
    digest_date: str
    status: str
    kind: str
    sent_at: str | None = None
    failed_reason: str | None = None
    created_at: datetime | None = None


class CoachDigestLogView(BaseModel):
    entries: list[CoachDigestLogEntryView]


class AdminGatewayView(BaseModel):
    stripe_connected: bool
    stripe_account_id_masked: str | None = None
    manual_methods: list[str]


class AdminGatewayConnectLinkView(BaseModel):
    url: str


class ReportsKpiResponse(BaseModel):
    active_students: int = 0
    attendance_rate_30d: float = 0.0
    dues_collected_mtd_cents: int = 0
    pending_waivers: int = 0


class AdminReportsAttendanceSummary(BaseModel):
    present_count: int = 0
    recorded_count: int = 0
    attendance_rate: float | None = None
    empty: bool = True


class AdminReportsSessionsSummary(BaseModel):
    scheduled_count: int = 0
    completed_count: int = 0
    cancelled_count: int = 0
    enrolled_seats: int = 0
    capacity: int = 0
    capacity_utilization: float | None = None
    waitlist_count: int = 0
    empty: bool = True


class AdminReportsExpenseCategory(BaseModel):
    category: str
    amount_cents: int
    count: int


class AdminReportsExpensesSummary(BaseModel):
    total_cents: int = 0
    by_category: list[AdminReportsExpenseCategory] = []


class AdminReportsCollectionsAgingBucket(BaseModel):
    label: str
    amount_cents: int
    family_count: int


class AdminReportsCollectionsRisk(BaseModel):
    overdue_family_count: int = 0
    overdue_cents: int = 0
    failed_payment_count: int = 0
    partial_payment_count: int = 0
    aging_buckets: list[AdminReportsCollectionsAgingBucket] = []


class AdminReportsProfitAndLoss(BaseModel):
    revenue_cents: int = 0
    coach_payroll_cents: int | None = None
    rent_cents: int = 0
    misc_expenses_cents: int = 0
    net_profit_cents: int | None = None
    profit_margin: float | None = None


class AdminReportsPayrollSummary(BaseModel):
    estimated_cents: int | None = None
    approved_cents: int | None = None
    paid_cents: int | None = None
    unpaid_cents: int | None = None
    blocked_by: str | None = None


class AdminReportsDashboardResponse(BaseModel):
    period: str
    cash_collected_cents: int = 0
    outstanding_dues_cents: int = 0
    attendance: AdminReportsAttendanceSummary = Field(default_factory=AdminReportsAttendanceSummary)
    sessions: AdminReportsSessionsSummary = Field(default_factory=AdminReportsSessionsSummary)
    expenses: AdminReportsExpensesSummary = Field(default_factory=AdminReportsExpensesSummary)
    collections_risk: AdminReportsCollectionsRisk = Field(
        default_factory=AdminReportsCollectionsRisk
    )
    profit_and_loss: AdminReportsProfitAndLoss = Field(default_factory=AdminReportsProfitAndLoss)
    payroll: AdminReportsPayrollSummary = Field(default_factory=AdminReportsPayrollSummary)
    empty_states: list[str] = []


class AdminSessionEconomicsSummary(BaseModel):
    expected_revenue_cents: int = 0
    paid_cents: int = 0
    unpaid_cents: int = 0
    coach_payroll_cents: int = 0
    rent_cents: int = 0
    other_expenses_cents: int = 0
    expected_profit_cents: int = 0
    profit_margin: float | None = None


class AdminSessionEconomicsRow(BaseModel):
    session_id: str
    title: str
    coach_name: str | None = None
    active_enrollment_count: int = 0
    paid_student_count: int = 0
    unpaid_student_count: int = 0
    monthly_fee_cents: int = 0
    payable_occurrence_count: int = 0
    expected_revenue_per_occurrence_cents: int = 0
    expected_revenue_cents: int = 0
    paid_cents: int = 0
    unpaid_cents: int = 0
    coach_payroll_cents: int = 0
    rent_cents: int = 0
    other_expenses_cents: int = 0
    expected_profit_cents: int = 0
    profit_margin: float | None = None


class AdminSessionEconomicsResponse(BaseModel):
    period: str
    summary: AdminSessionEconomicsSummary = Field(default_factory=AdminSessionEconomicsSummary)
    sessions: list[AdminSessionEconomicsRow] = []
    empty_states: list[str] = []


# --- Analytics ---


class EnrollmentFunnelResponse(BaseModel):
    leads: int
    applied: int
    assessed: int
    confirmed: int
    dropped: int
    total_applications: int
    conversion_rate: float
    period: str | None = None


class AttendancePeriodPointView(BaseModel):
    period: str
    scheduled_count: int
    completed_count: int
    no_show_count: int
    completion_rate: float


class AttendanceTrendsResponse(BaseModel):
    periods: list[AttendancePeriodPointView]
    overall_completion_rate: float


class CoachUtilizationPointView(BaseModel):
    coach_id: str
    period: str
    hours: float
    payout_minor: int
    utilization_rate: float


class CoachUtilizationResponse(BaseModel):
    coaches: list[CoachUtilizationPointView]
    periods: list[str]
    total_payout_minor: int


# --- Enrollment Events ---


class EnrollmentEventDto(BaseModel):
    event_id: str
    event_type: str
    effective_date: str
    reason: str | None = None
    billing_policy: str | None = None
    billing_result: str | None = None
    credit_id: str | None = None
    refund_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class EnrollmentEventsResponse(BaseModel):
    enrollment_id: str
    events: list[EnrollmentEventDto]


# --- Email Campaigns ---


class SendCampaignAudience(BaseModel):
    type: Literal["academy", "session"]
    role: Literal["parent", "coach"] = "parent"
    session_id: str | None = None


class SendCampaignRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    audience: SendCampaignAudience


class SendCampaignResponse(BaseModel):
    campaign_id: str
    total_recipients: int
    sent_count: int
    failed_count: int
