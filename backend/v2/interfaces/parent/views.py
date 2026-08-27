"""Parent BFF view DTOs.

Parent-shaped — never includes academy-wide payment lists, coach payouts,
or admin-only fields. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Onboarding ---


class ParentProfileView(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str | None = None
    phone: str = ""


class ChildProfileView(BaseModel):
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    skill_level: Literal["beginner", "intermediate", "advanced", ""] = ""
    # Optional on the DTO — the wizard autosaves partial drafts per step.
    # Completeness is enforced at checkout, not here. Issue #380.
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    medical_notes: str = ""

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: str) -> str:
        if value == "":
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date_of_birth must be a valid ISO date") from exc
        return value


class WaiverView(BaseModel):
    version: str
    text: str


class ApplicationView(BaseModel):
    application_id: str
    status: str
    parent_profile: ParentProfileView
    child_profile: ChildProfileView
    selected_session_id: str | None
    waiver_accepted: bool
    expires_at: datetime


class PatchApplicationRequest(BaseModel):
    parent_profile: ParentProfileView | None = None
    child_profile: ChildProfileView | None = None
    selected_session_id: str | None = None
    accept_waiver: bool = False


class RegistrationWaiverView(BaseModel):
    """Active registration waiver for the parent onboarding stepper."""

    configured: bool
    version: str | None = None
    body: str | None = None


# --- Checkout ---


class StartCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str
    success_url: str
    cancel_url: str


class StartCheckoutResponse(BaseModel):
    payment_id: str
    redirect_url: str


class StartAutopayRequest(BaseModel):
    enrollment_id: str
    success_url: str
    cancel_url: str


class StartAutopayResponse(BaseModel):
    subscription_id: str
    checkout_session_id: str
    redirect_url: str


class BillingPortalRequest(BaseModel):
    return_url: str


class BillingPortalResponse(BaseModel):
    redirect_url: str


class StartInvoicePaymentRequest(BaseModel):
    success_url: str
    cancel_url: str
    # Opt into autopay for the covered enrollment(s) as part of this payment.
    # Defaults False so requests from older clients stay one-time-only.
    enroll_autopay: bool = False


class StartInvoicePaymentResponse(BaseModel):
    invoice_id: str
    redirect_url: str


class StartBalancePaymentRequest(BaseModel):
    success_url: str
    cancel_url: str
    # Opt into autopay for the covered enrollment(s) as part of this payment.
    # Defaults False so requests from older clients stay one-time-only.
    enroll_autopay: bool = False


class StartBalancePaymentResponse(BaseModel):
    redirect_url: str


class CheckoutStatusResponse(BaseModel):
    checkout_session_id: str
    payment_id: str | None = None
    status: str
    parent_id: str


class EnrollmentQuoteRequest(BaseModel):
    student_id: str | None = None
    session_id: str
    start_date: str | None = None


class EnrollmentQuoteResponse(BaseModel):
    snapshot_id: str
    quote_expires_at: datetime | None = None
    amount_due_cents: int
    monthly_price_cents: int
    billing_period: str
    total_eligible_classes_this_month: int
    billable_remaining_classes_this_month: int
    formula: str
    message: str
    next_billing_amount_cents: int
    next_billing_message: str


# --- Payments ---


class ParentPaymentView(BaseModel):
    payment_id: str
    amount_cents: int
    currency: str
    status: str
    refunded_cents: int
    created_at: datetime
    session_id: str | None
    stripe_invoice_id: str | None = None
    stripe_payment_intent_id: str | None = None
    # Ledger linkage (via payment_allocations) so the UI can label what the
    # payment paid for; None for legacy/unallocated payments.
    invoice_id: str | None = None
    invoice_period: str | None = None


class ParentPaymentHistoryResponse(BaseModel):
    payments: list[ParentPaymentView]


class ParentCreditView(BaseModel):
    credit_id: str
    type: str
    status: str
    amount_cents: int
    remaining_amount_cents: int
    currency: str
    reason: str
    expires_at: datetime | None = None


class ParentCreditBalanceResponse(BaseModel):
    balance_cents: int
    credits: list[ParentCreditView]


# --- Invoices ---


class ParentInvoiceView(BaseModel):
    invoice_id: str
    period: str
    status: str
    total_cents: int
    balance_due_cents: int
    currency: str
    due_date: date
    pdf_url: str | None = None
    created_at: datetime
    # Enrollment covered by this invoice so the UI can decide autopay opt-in
    # visibility; None for legacy/unlinked invoices.
    enrollment_id: str | None = None


class ParentInvoicesResponse(BaseModel):
    invoices: list[ParentInvoiceView]


class ParentInvoiceLineView(BaseModel):
    description: str
    label: str | None = None
    quantity: int
    unit_amount_cents: int
    amount_cents: int


class ParentInvoiceDetailView(ParentInvoiceView):
    lines: list[ParentInvoiceLineView]


# --- Children / attendance / progress ---


class ParentChildView(BaseModel):
    student_id: str
    full_name: str
    status: str
    active_session_count: int
    attended_count: int
    absent_count: int


class ParentEnrollmentView(BaseModel):
    enrollment_id: str
    student_id: str
    student_name: str
    session_id: str
    session_title: str
    status: str
    payment_mode: str | None = None
    subscription_status: str | None = None
    autopay_enrollment_status: str | None = None
    last_attempt_outcome: str | None = None
    last_attempt_at: datetime | None = None
    last_failure_code: str | None = None
    autopay_payment_method_type: str | None = None
    autopay_payment_method_label: str | None = None
    autopay_payment_method_last4: str | None = None
    autopay_setup_status: str | None = None


class ParentEnrollmentsResponse(BaseModel):
    enrollments: list[ParentEnrollmentView]


class PauseRequestView(BaseModel):
    pause_request_id: str
    enrollment_id: str
    parent_id: str
    period: str
    pause_kind: str = "fixed"
    resume_on: date | None = None
    review_on: date | None = None
    reason: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class PauseRequestsResponse(BaseModel):
    requests: list[PauseRequestView]


class CreatePauseRequest(BaseModel):
    enrollment_id: str
    period: str = ""
    pause_kind: str = "fixed"
    resume_on: date | None = None
    review_on: date | None = None
    reason: str = ""


class ParentChildrenResponse(BaseModel):
    children: list[ParentChildView]


class ParentAttendanceRecordView(BaseModel):
    attendance_id: str
    student_id: str
    student_name: str
    session_id: str
    session_title: str
    status: str
    marked_at: datetime
    coach_name: str | None = None


class ParentAttendanceResponse(BaseModel):
    records: list[ParentAttendanceRecordView]
    total: int
    limit: int
    offset: int


class ParentProgressNoteView(BaseModel):
    note_id: str
    student_id: str
    student_name: str
    session_id: str | None = None
    session_title: str | None = None
    coach_id: str | None = None
    coach_name: str | None = None
    body: str
    created_at: datetime


class ParentProgressResponse(BaseModel):
    notes: list[ParentProgressNoteView]
    total: int
    limit: int
    offset: int


# --- Waivers ---


class ParentWaiverStudentView(BaseModel):
    student_id: str
    student_name: str
    status: Literal["signed", "pending", "outdated", "not_required"]
    signed_at: datetime | None = None
    waiver_version: str | None = None


class ParentWaiverCurrentView(BaseModel):
    required: bool
    waiver_template_id: str | None = None
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentView] = []


class ParentWaiverAcceptRequest(BaseModel):
    signer_name: str | None = None


# --- Child schedule ---


class ParentScheduleEntryView(BaseModel):
    occurrence_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    coach_name: str | None = None


class ParentScheduleResponse(BaseModel):
    entries: list[ParentScheduleEntryView]
    total: int
    limit: int
    offset: int


# --- Billing Enrollments ---


class EnrollChildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str
    session_type_id: str
    success_url: str
    cancel_url: str


class BillingEnrollmentResponse(BaseModel):
    enrollment_id: str
    student_id: str
    parent_id: str
    session_type_id: str
    status: str
    redirect_url: str | None = None
    stripe_subscription_id: str | None = None
    billing_start_date: datetime
    enrolled_at: datetime


class CancelBillingEnrollmentResponse(BaseModel):
    enrollment_id: str
    status: str


# --- Sessions ---


class ParentAvailableSessionView(BaseModel):
    session_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int
    enrolled_count: int
    available_seats: int
    amount_cents: int


class ParentAvailableSessionsResponse(BaseModel):
    sessions: list[ParentAvailableSessionView]


# --- Academy info ---


class ParentAcademyView(BaseModel):
    display_name: str
    timezone: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    hours_text: str | None = None
    address: str | None = None
    logo_url: str | None = None


# ---------------------------------------------------------------------------
# Messages inbox (UIM13)
# ---------------------------------------------------------------------------


class ParentMessageView(BaseModel):
    message_id: str
    kind: Literal["dm", "announcement"]
    sender_persona: Literal["admin", "coach", "parent"]
    body: str
    created_at: datetime
    read: bool


class ParentMessagesResponse(BaseModel):
    messages: list[ParentMessageView]


class ParentMarkMessageReadResponse(BaseModel):
    status: Literal["ok"] = "ok"
# --- Self-service profile (issue #380) ---


class ParentProfileGapsView(BaseModel):
    """Required fields still missing, keyed the same way the frontend labels them."""

    parent: list[str] = []
    children: dict[str, list[str]] = {}
    is_complete: bool


class ParentSelfChildView(BaseModel):
    student_id: str
    full_name: str
    date_of_birth: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_notes: str | None = None
    # True when the parent has ticked "no known conditions or allergies" —
    # distinct from medical_notes being None, which means "never answered".
    no_medical_conditions: bool = False


class ParentSelfProfileResponse(BaseModel):
    user_id: str
    display_name: str
    email: str
    email_confirmed: bool
    phone: str | None = None
    children: list[ParentSelfChildView]
    gaps: ParentProfileGapsView


class UpdateParentProfileRequest(BaseModel):
    """Parent editing their own name/phone. Email is deliberately absent — it
    is the Firebase login identifier and is confirmed, not edited, here."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)


_MIN_BIRTH_YEAR_SPAN = 100


class UpdateParentChildRequest(BaseModel):
    """Parent editing their own child. Field allow-list is enforced by
    ``extra="forbid"`` — status, parent_id, level, etc. are never accepted
    from a parent, no matter what the payload contains."""

    model_config = ConfigDict(extra="forbid")

    date_of_birth: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=40)
    medical_notes: str | None = Field(default=None, max_length=1000)
    no_medical_conditions: bool = False

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is None:
            return value
        today = date.today()
        if value > today:
            raise ValueError("date_of_birth cannot be in the future")
        earliest = today.replace(year=today.year - _MIN_BIRTH_YEAR_SPAN)
        if value < earliest:
            raise ValueError("date_of_birth is implausibly far in the past")
        return value
