"""Admin BFF view DTOs.

Admin-shaped — academy-wide read fields included. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Sessions ---


class AdminSessionView(BaseModel):
    session_id: str
    coach_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int
    status: Literal["scheduled", "cancelled", "completed"]


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
    parent_id: str
    status: str


class AdminEnrollmentList(BaseModel):
    enrollments: list[AdminEnrollmentView]


class EditRosterAddRequest(BaseModel):
    session_id: str
    student_id: str
    parent_id: str
    full_name: str


# --- Waitlist ---


class AdminWaitlistEntry(BaseModel):
    waitlist_id: str
    session_id: str
    student_id: str
    parent_id: str
    joined_at: datetime
    status: str


class AdminWaitlistList(BaseModel):
    entries: list[AdminWaitlistEntry]


# --- Billing ---


class AdminPaymentView(BaseModel):
    payment_id: str
    parent_id: str
    session_id: str | None
    amount_cents: int
    currency: str
    status: str
    refunded_cents: int
    created_at: datetime


class AdminPaymentList(BaseModel):
    payments: list[AdminPaymentView]


class IssueRefundRequest(BaseModel):
    payment_id: str
    amount_cents: int | None = None
    reason: str = "admin_initiated"


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


class BroadcastRequest(BaseModel):
    body: str


class DMRequest(BaseModel):
    recipient_id: str
    body: str
