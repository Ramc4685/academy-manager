"""Parent BFF view DTOs.

Parent-shaped — never includes academy-wide payment lists, coach payouts,
or admin-only fields. Per docs/security-matrix.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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


# --- Checkout ---


class StartCheckoutRequest(BaseModel):
    application_id: str
    amount_cents: int
    success_url: str
    cancel_url: str


class StartCheckoutResponse(BaseModel):
    payment_id: str
    redirect_url: str


# --- Payments ---


class ParentPaymentView(BaseModel):
    payment_id: str
    amount_cents: int
    currency: str
    status: str
    refunded_cents: int
    created_at: datetime
    session_id: str | None


class ParentPaymentHistoryResponse(BaseModel):
    payments: list[ParentPaymentView]
