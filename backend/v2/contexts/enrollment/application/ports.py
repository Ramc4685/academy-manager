"""Enrollment application ports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal, Protocol

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    RosterEntry,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry


class SessionQuery(Protocol):
    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]: ...
    async def for_coach(self, coach_id: str) -> list[Session]: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def get_many(self, session_ids: list[str]) -> list[Session]: ...


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...

    async def list_for_session(self, session_id: str) -> list[SessionOccurrence]: ...

    async def list_for_coach_on_date(
        self,
        *,
        coach_id: str,
        on_date: date,
    ) -> list[SessionOccurrence]: ...

    async def list_for_coach_upcoming(
        self,
        *,
        coach_id: str,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[SessionOccurrence]: ...

    # Academy-wide variants of the two coach queries above, for coach
    # supervisors (admin/owner covering any session). Same tenant scope,
    # same cancelled filter, no coach filter.
    async def list_on_date(self, *, on_date: date) -> list[SessionOccurrence]: ...

    async def list_upcoming(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[SessionOccurrence]: ...

    async def list_for_session_between(
        self,
        *,
        session_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SessionOccurrence]: ...

    async def save_many(self, occurrences: list[SessionOccurrence]) -> None: ...

    async def cancel_scheduled(
        self,
        *,
        occurrence_id: str,
        reason: str,
        actor_id: str | None,
        now: datetime,
    ) -> SessionOccurrence | None:
        """CAS ``scheduled`` → ``cancelled`` for one date (issue #671); ``None``
        when the row is missing or no longer scheduled."""
        ...

    async def update_coach_assignment(
        self,
        *,
        occurrence_id: str,
        actual_coach_id: str | None = None,
        substitute_coach_id: str | None = None,
        assignment_reason: str | None = None,
    ) -> SessionOccurrence | None: ...


class EnrollmentQuery(Protocol):
    async def active_for_session(self, session_id: str) -> list[Enrollment]: ...

    async def for_session_in_statuses(
        self, session_id: str, statuses: list[str]
    ) -> list[Enrollment]:
        """Rows for a session in any of ``statuses`` (issue #651).

        ``CancelSession`` needs active AND paused rows: a paused family still
        holds a deferral, a scheduled resume and (from the billing side) an
        expectation of coming back, and cancelling only the active rows
        orphaned all of that.
        """

    async def is_active(self, session_id: str, student_id: str) -> bool: ...
    async def active_for_student(self, student_id: str) -> list[Enrollment]: ...


class StudentQuery(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class RosterQuery(Protocol):
    """Composed read of roster for a session."""

    async def for_session(self, session_id: str) -> list[RosterEntry]: ...


# --- Write-side ports (Wave 2+) ---


class SessionWriter(Protocol):
    async def get(self, session_id: str) -> Session | None: ...

    async def try_reserve_seat(self, session_id: str) -> bool:
        """Atomic capacity check + reserve. Returns False if at capacity."""

    async def release_seat(self, session_id: str) -> None: ...

    async def update_status(self, session_id: str, status: str) -> None: ...

    async def create(self, session: Session) -> None: ...

    async def update(self, session: Session) -> None: ...

    async def find_duplicate_recurring_series(
        self,
        *,
        title: str,
        location: str,
        coach_id: str,
        days_of_week: list[str],
        start_time: str,
        end_time: str,
        timezone: str,
        exclude_session_id: str | None = None,
    ) -> Session | None: ...


class EnrollmentWriter(Protocol):
    async def create(self, enrollment: Enrollment) -> None: ...

    async def create_if_absent(self, enrollment: Enrollment) -> bool: ...

    async def update_status(self, enrollment_id: str, status: str) -> None: ...

    async def update_session(self, enrollment_id: str, session_id: str) -> None: ...

    async def update_amount_cents(self, enrollment_id: str, amount_cents: int | None) -> None: ...

    async def add_skip_period(self, enrollment_id: str, period: str) -> None: ...

    async def set_enrolled_at_if_missing(
        self, enrollment_id: str, enrolled_at: datetime
    ) -> None: ...

    async def mark_withdrawn_if_open(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        """Atomically move an ``active``/``paused`` row to ``withdrawn`` and
        stamp ``withdrawal_date`` (issue #670).

        Returns the row AS IT WAS before the write, or ``None`` when the row
        was not open (already withdrawn/cancelled, or missing). The pre-image
        is the seat token: only the caller that flipped an ``active`` OR
        ``held`` row releases its seat (a ``paused`` pre-image never does —
        it already released when it paused), so a concurrent double-submit or
        a retry can never decrement ``reserved_seats`` twice.

        Widened by issue #697 to also accept a ``held`` pre-image status —
        Drop must work on a held enrollment.
        """

    async def mark_held_if_active(
        self,
        enrollment_id: str,
        *,
        started_at: datetime,
        return_on: date,
        expires_at: datetime,
        reason: str | None,
    ) -> Enrollment | None:
        """CAS ``active`` -> ``held`` (issue #697). ``reserved_seats`` is left
        untouched — the row keeps its seat. Returns the pre-image, or
        ``None`` when the row was not ``active``."""
        ...

    async def mark_active_if_held(self, enrollment_id: str) -> Enrollment | None:
        """CAS ``held`` -> ``active`` (Return, issue #697).

        MUST NOT call ``try_reserve_seat`` — the seat was never released.
        Returns the pre-image, or ``None`` when the row was not ``held``
        (already returned, reclaimed, or expired)."""
        ...

    async def delete_if_status(
        self, enrollment_id: str, *, allowed: frozenset[str]
    ) -> Enrollment | None:
        """CAS: hard-delete the row iff its status is in ``allowed``.
        Returns the pre-image so the caller knows whether to release a seat."""
        ...

    async def get(self, enrollment_id: str) -> Enrollment | None: ...

    async def find_for_session_student(
        self, session_id: str, student_id: str
    ) -> Enrollment | None: ...

    async def count_active_for_session(self, session_id: str) -> int:
        """How many active enrollment rows this session actually has.

        Needed on the write port so a refused `try_reserve_seat` can be
        explained: `reserved_seats` at capacity with a roster well under it is
        counter drift, not a full session, and the two need different
        admin-facing messages (issue #610).
        """


class StudentWriter(Protocol):
    async def upsert(self, student: Student) -> None: ...

    async def ensure_exists(self, student: Student) -> bool:
        """Insert the student if absent; never modify an existing row.

        `upsert` writes the whole model, which is right for the registration
        approval path (it owns the full profile) and catastrophic for the
        roster path: adding an already-known student re-sent every optional
        field as `None`, wiping date_of_birth, emergency contacts, medical
        notes and — worst — `student_user_id`, silently breaking that
        student's login (issue #610).

        Returns True when a row was created, False when one already existed.
        """


class WaitlistRepository(Protocol):
    async def add(self, entry: WaitlistEntry) -> None: ...

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None: ...

    async def update_status(self, waitlist_id: str, status: str) -> None: ...

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None: ...

    async def remove_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> None: ...


class EnrollmentEventRepository(Protocol):
    async def record(self, event: EnrollmentLifecycleEvent) -> None: ...

    async def list_for_enrollment(self, enrollment_id: str) -> list[EnrollmentLifecycleEvent]: ...


class EnrollmentBillingSync(Protocol):
    """Cross-context port (issue #651): tell billing that attendance stopped or
    resumed so it can void unpaid future-period invoices, move the autopay
    status and stop dunning ladders.

    INVARIANT — every transition that stops attendance (cancel, withdraw,
    session cancelled, pause) and every resume MUST call this port. A family
    must never be charged for a class they will not attend. Implementations
    are idempotent and never raise into the caller's write path.
    """

    async def apply(
        self,
        *,
        enrollment_id: str,
        transition: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]: ...


class EnrollmentAutopayLookup(Protocol):
    """Cross-context READ port (issue #674): billing's per-enrollment autopay
    status (``autopay_enrollment_status``: active / paused / disabled / setup
    states) keyed by enrollment id. Adapted in the composition root onto the
    billing repository; enrollment infrastructure never reads billing's
    collections directly. Ids with no billing record are simply absent.
    """

    async def autopay_status_by_enrollment(
        self, enrollment_ids: list[str]
    ) -> dict[str, str | None]: ...


class OccurrenceRosterCleanup(Protocol):
    """Drop a student's FUTURE one-time occurrence roster rows (issue #651).

    Make-up and trial approvals write ``occurrence_roster_entries`` that sit
    outside the enrollment row. When the enrollment is cancelled, withdrawn
    or the whole session is cancelled those rows would otherwise keep the
    student on a coach's day sheet for a class they no longer attend.
    Implementations are best-effort from the caller's point of view: the
    use cases wrap the call in catch/log/continue.
    """

    async def remove_future_for_student(
        self, *, session_id: str, student_id: str, after: datetime
    ) -> int: ...


class OccurrenceRosterPurge(Protocol):
    """Drop every one-time roster row for ONE cancelled date (issue #671).

    Returns the removed entries so the caller can re-open the make-up
    requests behind them. Best-effort from the use case's point of view.
    """

    async def remove_for_occurrence(self, occurrence_id: str) -> list[Any]: ...


class MakeupReopener(Protocol):
    """Put approved make-ups that targeted a cancelled date back to pending
    (issue #671) so an admin can offer another class.

    ``expires_at`` is mandatory: a re-opened request whose original window has
    already lapsed is flipped straight back to ``expired`` by the next sweep,
    so the family loses an entitlement the academy had granted.
    """

    async def reopen_for_target_occurrence(
        self, occurrence_id: str, *, expires_at: datetime
    ) -> int: ...


class TrialReopener(Protocol):
    """Put approved trials assigned to a cancelled date back to pending
    (issue #671). Returns the student ids so the families can be told."""

    async def reopen_for_assigned_occurrence(self, occurrence_id: str) -> list[str]: ...


class MakeupPolicyLookup(Protocol):
    """The academy's self-service policy, for the re-opened make-up window."""

    async def get_or_default(self) -> Any: ...


class OccurrenceBillingSync(Protocol):
    """Tell billing one dated class was called off (issue #671).

    Sibling of :class:`EnrollmentBillingSync`: a narrow port here, the adapter
    over the billing context's ``ApplyOccurrenceCancellation`` in
    ``composition/occurrence_cancellation.py``. The occurrence write has
    already committed when this runs; the use case logs a failure and stamps
    ``billing_result`` on the lifecycle event, but never reports the cancel
    as failed. Returns a summary dict (``credits`` keyed by enrollment id).
    """

    async def apply(
        self,
        *,
        occurrence_id: str,
        session_id: str,
        start_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]: ...


class OccurrenceCancellationNotifier(Protocol):
    """Tell the affected families and the coach one date is off (issue #671).

    Best-effort: implementations must not raise into the enrollment write.

    ``extra_student_ids`` are the make-up and trial students whose one-time
    seat for the date was just deleted — they have no enrollment on the
    session, so the roster audience misses them entirely and they would turn
    up at a closed gym. ``credited_student_ids`` are the families billing
    actually credited: the email may only promise a credit to them, and
    ``billing_warning`` carries a staff-facing note when the sync did not run
    at all.
    """

    async def occurrence_cancelled(
        self,
        *,
        session_id: str,
        occurrence_id: str,
        start_at: datetime,
        reason: str,
        actor_id: str | None,
        extra_student_ids: Sequence[str] = (),
        credited_student_ids: Sequence[str] = (),
        billing_warning: str | None = None,
    ) -> None: ...


#: What the admin chose for the money side of a withdrawal (issue #670).
WithdrawalOutcome = Literal["credit", "refund", "adjustment"]


class EnrollmentMoveBillingSync(Protocol):
    """Cross-context port (issue #669): tell billing an enrollment changed
    session so the CURRENT period is re-priced for the classes still to come
    (debit line / adjustment invoice / ledger credit). Later periods re-price
    through the monthly generator on their own.

    Same contract as ``EnrollmentBillingSync``: idempotent per
    (enrollment, period, from, to) and never raises into the caller's write
    path — the returned dict carries ``billing_result`` for the audit event.
    """

    async def apply_move(
        self,
        *,
        enrollment_id: str,
        from_session_id: str,
        to_session_id: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
        effective_date: date | None = None,
        move_seq: int = 0,
    ) -> dict[str, Any]: ...


class EnrollmentWithdrawalDecisionPort(Protocol):
    """Cross-context port (issue #670): the billing-side half of a withdrawal.

    ``WithdrawEnrollment`` is the only writer of the lifecycle transition; it
    calls this port AFTER winning the status CAS, so only one caller can ever
    reach the money side of a given withdrawal. The adapter lives in
    ``composition/lifecycle_billing.py``.

    Contract:

    * Implementations MUST NOT refuse a withdrawal. A family with nothing to
      credit is a zero-credit result (``credit_none`` plus a
      ``no_credit_reason``), never an exception: the row is already withdrawn
      by the time this runs, and a raise would strand it.
    * ``outcome == "credit"`` issues the early-withdrawal credit ledger entry
      (idempotent on the ledger: a retry returns the entry it already made,
      never a second one) and cancels the legacy Stripe subscription
      (best effort — a failed cancel is reported in ``metadata``).
    * ``refund`` / ``adjustment`` have no automation; the result must say so
      (``refund_manual`` / ``adjustment_manual``) rather than pretend a
      decision was recorded.
    * Returns ``billing_policy``, ``billing_result``, optional ``credit_id``
      and a ``metadata`` dict of strings, all copied onto the lifecycle event.
    """

    async def record_withdrawal_decision(
        self,
        *,
        enrollment: Enrollment,
        outcome: WithdrawalOutcome,
        effective_at: datetime,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any]: ...


class EnrollmentWelcomeNotifier(Protocol):
    """Tells a family they are on a roster (issue #613).

    The enrollment context must never import communications, so this Protocol
    is the seam: the adapter that renders and sends the welcome email lives in
    ``composition/enrollment_welcome_email.py``.

    Implementations are called on a best-effort basis — an approval or a
    roster add must never fail because a mail provider is down — so the call
    sites wrap this in catch/log/continue.
    """

    async def send_welcome(
        self,
        *,
        session_id: str,
        student_name: str,
        parent_user_id: str,
        parent_email: str | None = None,
    ) -> None: ...


#: What changed on a roster (issue #612). One vocabulary for every trigger, so
#: a new lifecycle path has to pick a value rather than invent an alert.
RosterChangeKind = Literal[
    "approved",  # a registration was approved into a session
    "added",  # an admin or coach put a student on the roster directly
    "promoted",  # a waitlisted student took an opened seat
    "moved",  # transferred between sessions (both rosters changed)
    "cancelled",  # enrollment cancelled/removed (admin or parent self-serve)
    # A parent scheduled an end-of-period cancel (#675): the child is STILL on
    # the roster until month end. Distinct from "cancelled" so a coach reading
    # the alert does not drop a student who is still attending — and so staff
    # are not told twice (once now, once when the scheduled cancel runs).
    "cancellation_scheduled",
    "withdrawn",  # enrollment withdrawn mid-term
    "paused",  # enrollment paused (seat released, billing stopped)
    "resumed",  # paused enrollment back on the roster
    "session_cancelled",  # the whole class was cancelled by the academy
]


class RosterChangeNotifier(Protocol):
    """Tells the people who run a session that its roster changed (#612).

    Sibling of :class:`EnrollmentWelcomeNotifier`, and deliberately the same
    shape: a one-method Protocol here, the adapter that resolves recipients
    and sends in ``composition/roster_notifications.py``, because the
    enrollment context may never import communications.

    Implementations are best-effort and MUST NOT be allowed to fail the
    enrollment write — every call site wraps this in catch/log/continue. A
    missed alert is recoverable; a cancellation that reports failure because a
    mail provider blipped is not.

    ``moved`` is a single call carrying both ``from_session_id`` and
    ``to_session_id``: one roster change, two rosters, and the adapter is what
    knows both coaches need telling.
    """

    async def roster_changed(
        self,
        *,
        change: RosterChangeKind,
        session_id: str,
        student_id: str,
        student_name: str | None = None,
        enrollment_id: str | None = None,
        from_session_id: str | None = None,
        to_session_id: str | None = None,
        actor_id: str | None = None,
        parent_user_id: str | None = None,
    ) -> None: ...


# --- Hold / departure ports (issue #697) --------------------------------


class EnrollmentDeparturePolicyLookup(Protocol):
    """The academy's departure policy (max hold days, reclaim rule, ...)."""

    async def get_or_default(self) -> Any: ...


class HoldRepository(Protocol):
    """Read/claim over ``held`` enrollment rows for the reclaim algorithm.

    Lives beside ``EnrollmentWriter`` rather than folded into it: the reclaim
    CAS operates on a different predicate shape (session + status +
    unclaimed) with a deterministic sort, and keeping it a separate Protocol
    is what let the fake enforce "never return the same document twice"
    without also having to fake every other enrollment-writer method.
    """

    async def claim_longest_held(
        self, *, session_id: str, now: datetime, requested_by: str
    ) -> Enrollment | None:
        """Atomically claim the longest-held row for this session:
        ``held`` -> ``reclaim_pending``, ordered by
        ``(hold_started_at ASC, enrollment_id ASC)``. Returns the pre-image,
        or ``None`` when there is no unclaimed held row for this session.
        Never returns the same document twice."""
        ...

    async def finalize_reclaim(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        """CAS ``reclaim_pending`` -> ``withdrawn``. Returns the pre-image."""
        ...

    async def list_stalled(self, *, older_than: datetime) -> list[Enrollment]:
        """Rows stuck in ``reclaim_pending`` whose claim is older than the
        cutoff (crash recovery, see ``ProcessStalledReclaims``)."""
        ...

    async def list_due_for_reminder(self) -> list[Enrollment]:
        """Every ``held`` row (used by ``SendHoldReminders`` to compute which
        reminder, if any, is due for each — see the use case for the math)."""
        ...

    async def list_expired(self, *, now: datetime) -> list[Enrollment]:
        """``held`` rows whose ``hold_expires_at`` has passed."""
        ...


class HoldNotifier(Protocol):
    """Best-effort family email for hold lifecycle events. Never raises into
    the caller's write path. Implementations claim before sending; see
    ``communications/infrastructure/digest_claim.py`` for why the claim, not
    the send, is what makes this idempotent."""

    async def hold_reclaimed(
        self,
        *,
        enrollment_id: str,
        hold_seq: int,
        session_id: str,
        student_id: str,
        hold_started_at: datetime,
        reason: Literal["reclaimed", "expired"],
        requested_by: str | None,
        billing_result: str | None,
    ) -> None: ...

    async def hold_reminder(
        self,
        *,
        enrollment_id: str,
        hold_seq: int,
        notice_index: int,
        session_id: str,
        student_id: str,
        hold_started_at: datetime,
        hold_return_on: date,
        hold_expires_at: datetime,
    ) -> None: ...
