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
#:
#: Issue #699 (vocabulary migration) adds "dropped" and "deleted" as the
#: canonical spellings of "withdrawn" and "cancelled" respectively. Per the
#: departures design contract §5.4:
#:   - "withdrawn" -> "dropped" and "cancelled" -> "deleted" are lossless
#:     renames and ARE performed (see canonical_status() below).
#:   - "paused" -> "held" is explicitly REFUSED: a legacy paused row already
#:     released its seat, while held rows are counted in reserved_seats, so
#:     renaming would silently under-count the seat and let a class over-admit
#:     by one per migrated row. Legacy "paused" rows keep their status and are
#:     retired by attrition.
#: Both old and new spellings are accepted here for one release so a rollback
#: survives (dual-read); write paths move to the new spelling only (see
#: mongo_enrollment_writer.py, admin_writes.py, coach_roster_writes.py,
#: mongo_hold_repo.py). The schema validators (migrations 0132/0133) never
#: constrained `enrollments.status` or `enrollment_events.event_type` to an
#: enum — both are unconstrained `bsonType: "string"` — so this rename needs
#: no validator widening, unlike the #657/#658 failure mode it is modeled on.
EnrollmentStatus = Literal[
    "active",
    "paused",
    "held",
    "reclaim_pending",
    "cancelled",
    "deleted",
    "withdrawn",
    "dropped",
]
SessionStatus = Literal["scheduled", "cancelled", "completed"]
SessionOccurrenceStatus = Literal["scheduled", "cancelled", "completed"]

#: Pure mapping from a legacy stored spelling to its canonical (#699) one.
#: Identity for every other value, including "paused" (deliberately never
#: mapped to "held" — see the module docstring above). Every reader that
#: groups or displays enrollment status by its terminal outcome should
#: normalize through this function rather than comparing to a bare string,
#: so it reads legacy ("withdrawn"/"cancelled") and freshly-written
#: ("dropped"/"deleted") rows identically.
_LEGACY_TO_CANONICAL_STATUS: Final[dict[str, str]] = {
    "withdrawn": "dropped",
    "cancelled": "deleted",
}


def canonical_status(value: str) -> str:
    """Normalize a stored enrollment status to its #699 canonical spelling.

    ``canonical_status("withdrawn") == canonical_status("dropped") == "dropped"``
    ``canonical_status("cancelled") == canonical_status("deleted") == "deleted"``
    Every other value (including "paused") is returned unchanged.
    """
    return _LEGACY_TO_CANONICAL_STATUS.get(value, value)


#: Statuses whose row is counted in sessions.reserved_seats (issue #697).
#: No module outside this file and the CAS filter builders in
#: infrastructure/ may compare an enrollment status to a bare string literal
#: for seat purposes — use these frozensets instead (structural test
#: tests/structural/test_enrollment_status_predicates.py enforces this).
SEAT_HOLDING: Final[frozenset[str]] = frozenset({"active", "held"})

#: Statuses whose row has already given its seat back. Disjoint from
#: SEAT_HOLDING; together with "reclaim_pending" (a transient in-flight
#: state, neither holding nor released until finalize() runs) they cover
#: every EnrollmentStatus member. Carries BOTH spellings of the two renamed
#: terminal statuses (issue #699 dual-read era) — a row written by
#: yesterday's code ("withdrawn"/"cancelled") and one written by today's
#: ("dropped"/"deleted") must both be recognized as seatless.
SEATLESS: Final[frozenset[str]] = frozenset(
    {"paused", "cancelled", "deleted", "withdrawn", "dropped"}
)

# --------------------------------------------------------------------------
# Issue #642: the closed status vocabulary and its derived predicates.
#
# Before this, every reader spelled its own set at the point of use, so
# "paused" meant "keeps the seat" to one, "released it" to another and "still
# bill them" to a third — thirteen readers excluded it, six included it, and
# no two referenced a shared definition. Each frozenset below answers exactly
# ONE question about a row, and is the only place that answer is written
# down. ``tests/structural/test_enrollment_status_predicates.py`` bans
# hand-rolled status sets anywhere else under contexts/enrollment/ and
# re-checks the partitions here against the vocabulary.
#
# Adding a status to ``EnrollmentStatus`` therefore forces a decision: it has
# to be classified into the seat partition and the lifecycle partition, or
# the structural test fails. That is the point — an unclassified status used
# to inherit whichever meaning each ``$nin`` filter happened to give it.
# --------------------------------------------------------------------------

#: Every value ``enrollments.status`` may hold, as a runtime set. Kept in
#: lockstep with the ``EnrollmentStatus`` Literal by the structural test,
#: which is what the Literal alone cannot do — a Literal is invisible to the
#: Mongo validator and to any ``$in`` filter built at runtime.
ENROLLMENT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "active",
        "paused",
        "held",
        "reclaim_pending",
        "cancelled",
        "deleted",
        "withdrawn",
        "dropped",
    }
)

#: The in-flight state of a reclaim claim (issue #697): the row has neither
#: kept nor released its seat until ``SeatBroker.finalize()`` resolves it.
#: Named rather than spelled inline so the seat partition below reads as the
#: three-way split it is.
RECLAIM_PENDING: Final[str] = "reclaim_pending"

#: Written by ``MongoEnrollmentWriter.delete_if_status`` as a CAS marker in
#: the instant between "this row is mine to delete" and the delete itself.
#: NOT a status — no reader may branch on it — but it does reach the
#: collection, so the Mongo validator enum has to admit it (see migration
#: 0175; a validator that omitted it would turn every hard delete into a
#: write error, the #657 failure mode).
TRANSIENT_DELETING_STATUS: Final[str] = "__deleting__"

#: What the ``enrollments.status`` validator enum permits: the vocabulary
#: plus the transient delete marker.
STORED_ENROLLMENT_STATUSES: Final[frozenset[str]] = ENROLLMENT_STATUSES | {
    TRANSIENT_DELETING_STATUS
}

#: The two spellings of "the family withdrew" across the #699 dual-read era
#: (legacy "withdrawn", canonical "dropped"), and of "the enrollment was
#: cancelled/removed" (legacy "cancelled", canonical "deleted"). A reader
#: that wants the withdrawal date rather than the cancellation date keys off
#: the first; one that wants either outcome uses TERMINAL.
DROPPED_SPELLINGS: Final[frozenset[str]] = frozenset({"withdrawn", "dropped"})
DELETED_SPELLINGS: Final[frozenset[str]] = frozenset({"cancelled", "deleted"})

#: Attendance has stopped for good — the row is history. "paused" is
#: deliberately NOT here (a pause is an intermission, not an ending, #651),
#: and neither is "held". A transfer moves a row in place without a status
#: change, so it never lands here either.
TERMINAL: Final[frozenset[str]] = DROPPED_SPELLINGS | DELETED_SPELLINGS

#: The row has not ended: an admin action (cancel, withdraw, transfer, hold,
#: pause, resume) may still act on it. Complement of TERMINAL, minus the
#: transient reclaim state that no admin surface should race against.
LIVE: Final[frozenset[str]] = frozenset({"active", "paused", "held"})

#: Complement of TERMINAL over the whole vocabulary — LIVE plus the
#: in-flight reclaim. This is the set a *display* surface wants ("current
#: enrollments"), where showing a row mid-reclaim is right and racing a
#: write against it is not.
NON_TERMINAL: Final[frozenset[str]] = ENROLLMENT_STATUSES - TERMINAL

#: Rows monthly invoice generation charges for. "paused" is excluded
#: (issue #651 stopped billing open-ended pauses, the original #642
#: complaint) and so is "held".
#:
#: NOT yet consulted by ``contexts/billing`` — that reader still builds its
#: own filter and is out of scope for this slice by owner decision; see the
#: follow-up issue linked from PR #642. Declared here anyway so the contract
#: has a single written form for that migration to move onto, rather than
#: being re-derived from the billing pipeline a third time.
BILLABLE: Final[frozenset[str]] = frozenset({"active"})

#: Rows the class roster shows as currently enrolled. Same members as
#: SEAT_HOLDING today and deliberately a separate name: "occupies a seat" and
#: "appears on the roster" are different questions that happen to share an
#: answer, and #714 (held students vanished from the admin roster) was caused
#: by a reader assuming they were the same question.
ROSTER_VISIBLE: Final[frozenset[str]] = SEAT_HOLDING

#: Rows that appear on a coach's attendance sheet. The sheet is taken off the
#: roster, so this tracks ROSTER_VISIBLE by construction rather than by
#: coincidence — if the roster ever shows a status the coach must not mark,
#: this is where the two part company.
ATTENDANCE_VISIBLE: Final[frozenset[str]] = ROSTER_VISIBLE

#: "Still a live commitment for this student" as the pre-#697 readers meant
#: it: active, or paused (seat released but the family has not left, #641).
#: Narrower than LIVE because it predates "held"; kept as its own name so the
#: readers that genuinely want the old two-status answer are distinguishable
#: from the ones that were never widened for holds and should be.
ACTIVE_OR_PAUSED: Final[frozenset[str]] = frozenset({"active", "paused"})


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
    # Set when SeatBroker.acquire's own finalize_reclaim call raised (a Mongo
    # blip, a primary step-down) AFTER claiming this row but BEFORE the
    # withdrawal committed — the requester's transaction failed too, so
    # nobody actually received this seat. Distinguishes a genuine orphan from
    # a real, completed hand-over for the stalled-reclaim crash-recovery
    # sweep, which otherwise cannot tell the two apart from `hold_reclaim_for`
    # alone (see ProcessStalledReclaims).
    hold_reclaim_failed_at: datetime | None = None


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
