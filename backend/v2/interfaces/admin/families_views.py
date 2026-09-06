"""Request/response models for ``/admin/families/{parent_id}/…``.

Field names follow spec §3.2 of
``docs/superpowers/specs/2026-09-05-family-billing-design.md``. The read model hands
back plain dicts; these models shape them and drop anything unnamed (``extra="ignore"``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AutopayState = Literal["on", "off", "partial", "needs_consent"]
RegistrationState = Literal["registered", "invited", "not_invited"]
FamilyAction = Literal["send_invite", "autopay_on", "autopay_off", "send_invoice", "record_payment"]
InvoiceAction = Literal["send", "record_payment", "charge_card", "void", "refund", "discount_once"]
EnrollmentAction = Literal["recurring_discount"]
TimelineKind = Literal["money", "admin", "lifecycle", "comms"]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FamilyParent(_View):
    parent_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class FamilyLastPayment(_View):
    amount_cents: int
    method: str | None = None
    paid_at: str | None = None
    invoice_ids: list[str] = []


class FamilyLastFailure(_View):
    code: str | None = None
    at: str | None = None


class FamilyAutopay(_View):
    state: AutopayState
    active_count: int
    total_count: int
    card_last4: str | None = None
    card_label: str | None = None
    next_charge_on: str | None = None
    next_charge_invoice_id: str | None = None
    last_failure: FamilyLastFailure | None = None


class FamilyRegistration(_View):
    state: RegistrationState
    card_on_file: bool
    last_invited_at: str | None = None


class FamilyEnrollmentCounts(_View):
    active: int
    paused: int
    cancelled: int


class FamilyHeader(_View):
    balance_cents: int
    open_invoice_count: int
    available_credit_cents: int
    last_payment: FamilyLastPayment | None = None
    autopay: FamilyAutopay
    registration: FamilyRegistration
    enrollment_counts: FamilyEnrollmentCounts


class FamilyEnrollment(_View):
    enrollment_id: str
    session_id: str | None = None
    session_title: str | None = None
    schedule: str | None = None
    status: str
    monthly_price_cents: int | None = None
    override_price_cents: int | None = None
    autopay_status: str | None = None
    recurring_discount: dict[str, Any] | None = None
    resume_on: str | None = None
    actions: list[EnrollmentAction] = []


class FamilyStudent(_View):
    student_id: str
    name: str
    status: str | None = None
    enrollments: list[FamilyEnrollment] = []


class FamilyDelivery(_View):
    status: str
    last_sent_at: str | None = None
    kind: Literal["invoice", "autopay_notice"]


class FamilyAllocation(_View):
    payment_id: str
    amount_cents: int
    method: str | None = None
    paid_at: str | None = None
    stripe_payment_intent_id: str | None = None


class FamilyCredit(_View):
    credit_id: str
    amount_cents: int


class FamilyInvoice(_View):
    invoice_id: str
    invoice_number: str | None = None
    period: str
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    status: str
    total_cents: int
    paid_cents: int
    balance_due_cents: int
    due_date: str | None = None
    created_at: str | None = None
    paid_at: str | None = None
    voided_at: str | None = None
    void_reason: str | None = None
    settlement_unlinked: bool = False
    delivery: FamilyDelivery
    allocations: list[FamilyAllocation] = []
    credits: list[FamilyCredit] = []
    chargeable: bool = False
    actions: list[InvoiceAction] = []


class FamilyTimelineEntry(_View):
    at: str
    kind: TimelineKind
    code: str
    summary: str
    invoice_id: str | None = None
    invoice_ids: list[str] = []
    enrollment_id: str | None = None
    student_name: str | None = None
    actor_id: str | None = None
    reason: str | None = None
    amount_cents: int | None = None
    muted: bool = False


class AdminFamilyBillingView(_View):
    generated_at: str
    timezone: str
    today: str
    parent: FamilyParent
    header: FamilyHeader
    students: list[FamilyStudent] = []
    invoices: list[FamilyInvoice] = []
    timeline: list[FamilyTimelineEntry] = []
    actions: list[FamilyAction] = []
    warnings: list[str] = []


class PauseFamilyAutopayRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=120)


class PauseFamilyAutopayResponse(BaseModel):
    paused_count: int
    active_count_before: int
    warnings: list[str] = []
