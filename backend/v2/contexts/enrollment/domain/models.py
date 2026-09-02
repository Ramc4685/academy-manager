"""Enrollment domain — read-side slice for Wave 1A.

Aggregates: Session, Enrollment, Student. Write-side (create session, edit
roster, waitlist promotion) lands in Wave 2/3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.v2.shared.security.external_url import validate_external_url

EnrollmentStatus = Literal["active", "paused", "cancelled", "withdrawn"]
SessionStatus = Literal["scheduled", "cancelled", "completed"]
SessionOccurrenceStatus = Literal["scheduled", "cancelled", "completed"]


class Session(BaseModel):
    """A scheduled training session.

    Per data-ownership.md, the Enrollment context is the sole writer for
    `sessions`. Coaching reads this aggregate for the today screen.
    """

    model_config = {"frozen": True}

    session_id: str
    academy_id: str
    coach_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int = Field(ge=1)
    amount_cents: int | None = Field(default=None, ge=0)
    status: SessionStatus = "scheduled"
    days_of_week: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None

    # --- Communication pack (issue #613) ---
    # Optional, per-session onboarding facts a family needs on day one. Every
    # field defaults to None and *nothing* here gets a stand-in default: a
    # blank value must read as "not configured" so the welcome email can omit
    # the section rather than emailing a placeholder.
    whatsapp_group_link: str | None = Field(default=None, max_length=2048)
    venue_address: str | None = Field(default=None, max_length=500)
    parking_notes: str | None = Field(default=None, max_length=500)
    what_to_bring: str | None = Field(default=None, max_length=500)
    arrival_minutes_before: int | None = Field(default=None, ge=0, le=120)
    coach_contact_policy: str | None = Field(default=None, max_length=500)
    absence_policy: str | None = Field(default=None, max_length=1000)

    @field_validator("whatsapp_group_link")
    @classmethod
    def _validate_group_link(cls, value: str | None) -> str | None:
        """The invariant, not the UX check.

        The interface request models run the same validator so a bad paste is
        a 422; this one makes "only an http(s) link is ever persisted" true
        for every writer, including migrations and scripts. The link is
        rendered as an email ``href``, where escaping alone would not stop a
        ``javascript:`` scheme.
        """
        return validate_external_url(value, field_label="WhatsApp group link")


class SessionOccurrence(BaseModel):
    """One dated occurrence produced from a recurring session template."""

    model_config = {"frozen": True}

    occurrence_id: str
    academy_id: str
    session_id: str
    start_at: datetime
    end_at: datetime
    status: SessionOccurrenceStatus = "scheduled"
    scheduled_coach_id: str
    actual_coach_id: str | None = None
    substitute_coach_id: str | None = None
    is_billable: bool = True
    is_payable: bool = True
    cancellation_reason: str | None = None
    template_session_id: str | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> SessionOccurrence:
        if self.end_at <= self.start_at:
            raise ValueError("session occurrence end_at must be after start_at")
        return self


class Student(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    academy_id: str
    parent_id: str
    full_name: str
    date_of_birth: str | None = None
    # Issue #380: carried through from registration (onboarding.ChildProfile)
    # on approval, and editable by the parent afterwards via the self-service
    # profile. None means "not yet supplied", same convention as date_of_birth.
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_notes: str | None = None
    # UIM12: the identity-context user_id linked to this student's own login,
    # set once by `ProvisionStudentLogin`. `None` means no student login has
    # been provisioned (the default, and the common case pre-UIM12). One
    # user per student per academy — link time enforces this is only ever
    # set once (see `MongoStudentWriter.link_student_user`).
    student_user_id: str | None = None


class Enrollment(BaseModel):
    """A student's enrollment in a session."""

    model_config = {"frozen": True}

    enrollment_id: str
    academy_id: str
    session_id: str
    student_id: str
    status: EnrollmentStatus = "active"
    enrolled_at: datetime | None = None
    created_at: datetime | None = None
    # Registration approvals bind their generated artifact to one onboarding
    # application so a different pending application can never recover it.
    registration_application_id: str | None = None
    registration_student_lock: str | None = None
    # Self-cancel audit trail (R4). Always written together by
    # ``SelfCancelEnrollment`` — never a silent state change. ``cancelled_by``
    # distinguishes parent self-cancel from admin-initiated cancellation (the
    # existing ``CancelEnrollment``/``WithdrawEnrollment`` admin paths leave
    # these unset).
    cancelled_by: Literal["admin", "parent"] | None = None
    cancellation_reason: str | None = None
    cancellation_policy_snapshot: dict[str, Any] | None = None
    cancelled_at: datetime | None = None


class RosterEntry(BaseModel):
    """Pair of (enrollment, student) joined for roster display."""

    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str
    full_name: str
    status: EnrollmentStatus
