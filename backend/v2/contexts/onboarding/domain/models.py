"""Onboarding domain — Application aggregate + Waiver.

State machine (mirrors legacy):

    DRAFT
      ├─→ CHECKOUT_PENDING ─→ CHECKOUT_EXPIRED
      │                    └─→ PENDING_APPROVAL
      │                    └─→ CAPACITY_FAILED_REFUNDING ─→ REFUNDED
      │                                                  └─→ CAPACITY_FAILED_REFUND_FAILED
      └─→ ABANDONED (TTL expired without checkout)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

ApplicationStatus = Literal[
    "DRAFT",
    "CHECKOUT_PENDING",
    "CHECKOUT_EXPIRED",
    "PENDING_APPROVAL",
    "CAPACITY_FAILED_REFUNDING",
    "REFUNDED",
    "CAPACITY_FAILED_REFUND_FAILED",
    "ABANDONED",
]


class ParentProfile(BaseModel):
    model_config = {"frozen": True}
    first_name: str = ""
    last_name: str = ""
    email: EmailStr | None = None
    phone: str = ""


class ChildProfile(BaseModel):
    model_config = {"frozen": True}
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""  # YYYY-MM-DD
    skill_level: Literal["beginner", "intermediate", "advanced", ""] = ""


class WaiverAcceptance(BaseModel):
    model_config = {"frozen": True}
    waiver_version: str
    content_hash: str
    accepted_at: datetime


class Application(BaseModel):
    model_config = {"frozen": True}

    application_id: str
    academy_id: str
    parent_user_id: str
    parent_email: EmailStr
    status: ApplicationStatus = "DRAFT"
    parent_profile: ParentProfile = Field(default_factory=ParentProfile)
    child_profile: ChildProfile = Field(default_factory=ChildProfile)
    selected_session_id: str | None = None
    waiver_acceptance: WaiverAcceptance | None = None
    stripe_checkout_session_id: str | None = None
    payment_id: str | None = None
    expires_at: datetime  # 7d TTL after creation
    created_at: datetime
    updated_at: datetime


class Waiver(BaseModel):
    model_config = {"frozen": True}

    waiver_id: str
    academy_id: str
    version: str            # e.g. "2026.1"
    text: str
    content_hash: str
    effective_from: datetime
