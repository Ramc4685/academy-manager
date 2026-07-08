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
    "APPROVED",
    "WAITLISTED",
    "DECLINED",
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
    waiver_template_id: str | None = None  # ADR-0007: pins acceptance to immutable template version


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
    student_id: str | None = None
    enrollment_id: str | None = None
    waitlist_id: str | None = None
    decision_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    # "YYYY-MM" billed $0 at checkout; see admin_registration_review
    zero_quote_period: str | None = None
    expires_at: datetime  # 7d TTL after creation
    created_at: datetime
    updated_at: datetime


class Waiver(BaseModel):
    model_config = {"frozen": True}

    waiver_id: str
    academy_id: str
    version: str  # e.g. "2026.1"
    text: str
    content_hash: str
    effective_from: datetime


# ---------------------------------------------------------------------------
# Wave 4 — per-student waiver model
#
# ADR-0007 / SaaS architecture assessment §8: admins need to be able to answer
# "what exact waiver did this student sign?" That requires:
#
#   * an immutable ``WaiverTemplate`` (one row per published version), and
#   * a ``WaiverSignature`` row per (template, student), pointing to the
#     stored PDF/image via ``artifact_id``.
#
# The legacy ``Waiver`` aggregate above is kept for backward-compat with the
# v2 onboarding application use case. New code should target the per-student
# model.
# ---------------------------------------------------------------------------


WaiverTemplateStatus = Literal["draft", "active", "superseded", "retired"]


class WaiverTemplate(BaseModel):
    """Immutable, published version of a waiver's body + metadata.

    A template is identified by ``waiver_template_id``. Once a template is in
    state ``active`` and any signature references it, callers MUST NOT mutate
    its ``content_hash`` or ``body``. To change wording, publish a new
    template and mark the previous one ``superseded``.
    """

    model_config = {"frozen": True}

    waiver_template_id: str
    academy_id: str
    name: str
    version: str  # e.g. "2026.1"
    content_hash: str
    body: str
    effective_from: datetime
    expires_at: datetime | None = None
    status: WaiverTemplateStatus = "active"


class WaiverSignature(BaseModel):
    """Per-student signature.

    Notes:
        * ``waiver_template_id`` pins the signature to an immutable template
          version. Hash drift between the signature and the template surfaces
          a data-integrity problem.
        * ``content_hash`` is captured at sign-time to detect template
          tampering or accidental backfill writes.
        * ``artifact_id`` is the storage pointer to the rendered signed
          document (PDF/image). The artifact store is separate from this
          aggregate.
    """

    model_config = {"frozen": True}

    waiver_signature_id: str
    academy_id: str
    waiver_template_id: str
    student_id: str
    parent_user_id: str
    signed_at: datetime
    signer_name: str
    signer_email: EmailStr
    content_hash: str
    ip_address: str | None = None
    user_agent: str | None = None
    artifact_id: str | None = None
    expires_at: datetime | None = None
