"""Enrollment domain — read-side slice for Wave 1A.

Aggregates: Session, Enrollment, Student. Write-side (create session, edit
roster, waitlist promotion) lands in Wave 2/3.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.v2.shared.security.external_url import validate_external_url

#: Issue #697 adds "held" (keeps the seat) and "reclaim_pending" (the
#: transient in-flight state of a reclaim claim, see application/seat_broker.py).
#: "held" is NOT a rename of "paused" — paused releases the seat, held does
#: not — see the departures design contract §2.1.
EnrollmentStatus = Literal["active", "paused", "held", "reclaim_pending", "cancelled", "withdrawn"]
SessionStatus = Literal["scheduled", "cancelled", "completed"]
SessionOccurrenceStatus = Literal["scheduled", "cancelled", "completed"]

#: Statuses whose row is counted in sessions.reserved_seats (issue #697).
#: No module outside this file and the CAS filter builders in
#: infrastructure/ may compare an enrollment status to a bare string literal
#: for seat purposes — use these frozensets instead (structural test
#: tests/structural/test_enrollment_status_predicates.py enforces this).
SEAT_HOLDING: Final[frozenset[str]] = frozenset({"active", "held"})

#: Statuses whose row has already given its seat back. Disjoint from
#: SEAT_HOLDING; together with "reclaim_pending" (a transient in-flight
#: state, neither holding nor released until finalize() runs) they cover
#: every EnrollmentStatus member.
SEATLESS: Final[frozenset[str]] = frozenset({"paused", "cancelled", "withdrawn"})


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
    # Assistant coaches (role ``assistant_coach``): helpers who get the coach
    # surface for THIS session only (attendance, skills, notes). Copied onto
    # every generated occurrence and re-synced onto future ones when edited.
    # Never consulted by payroll, which pays actual_coach_id else
    # scheduled_coach_id. Missing on legacy docs → empty.
    assistant_coach_ids: tuple[str, ...] = ()

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
    # Issue #671: stamped by ``CancelSessionOccurrence`` when ONE dated class
    # is called off (rain-out, coach sick). ``cancelled_by`` is the admin's
    # user id; a whole-session cancel (#467) leaves both unset and writes
    # ``cancellation_reason="session_cancelled"`` instead.
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None
    template_session_id: str | None = None
    # Snapshot of the session's assistants when the occurrence was generated
    # or last re-synced; the attendance use cases treat these ids like an
    # assignment. Not a payroll field.
    assistant_coach_ids: tuple[str, ...] = ()

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
    # Issue #675: an ``end_of_period`` parent self-cancel does NOT flip
    # ``status`` — the family keeps the seat, roster and schedule through the
    # month they paid for. It stamps the date the scheduled
    # ``cancel_at_period_end`` action will run instead; the processor clears
    # it when it performs the real cancel. Rosters stay status-only and read
    # this marker only to show "ends <date>".
    pending_cancellation_at: datetime | None = None
    pending_cancellation_requested_at: datetime | None = None

    # --- Hold fields (issue #697) ---
    # All default to None/0 so every existing row validates unchanged.
    hold_started_at: datetime | None = None  # when this hold began; the reclaim sort key
    hold_return_on: date | None = None  # required to start a hold; the promised return
    hold_expires_at: datetime | None = None  # snapshot: hold_started_at + policy.max_hold_days
    hold_reason: str | None = None
    hold_seq: int = 0  # +1 on every hold START; part of every email idempotency key
    hold_reclaim_claimed_at: datetime | None = None  # set by the reclaim CAS; None while claimable
    hold_reclaim_for: str | None = None  # the requester the seat was handed to (audit)


class RosterEntry(BaseModel):
    """Pair of (enrollment, student) joined for roster display."""

    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str
    full_name: str
    status: EnrollmentStatus
    # Issue #675: set while a parent's end-of-period cancel is pending.
    pending_cancellation_at: datetime | None = None
    # Issue #697: so the roster can show "On hold until <return_on>".
    hold_return_on: date | None = None
