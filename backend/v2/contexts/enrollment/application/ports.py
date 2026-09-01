"""Enrollment application ports."""

from __future__ import annotations

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

    async def list_for_session_between(
        self,
        *,
        session_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SessionOccurrence]: ...

    async def save_many(self, occurrences: list[SessionOccurrence]) -> None: ...

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


class EnrollmentLifecycleBillingPort(Protocol):
    async def record_move_proration(
        self,
        *,
        enrollment: Enrollment,
        from_session_id: str,
        to_session_id: str,
        effective_at: datetime,
        actor_id: str,
        reason: str | None,
    ) -> dict[str, Any]: ...

    async def record_withdrawal_decision(
        self,
        *,
        enrollment: Enrollment,
        outcome: str,
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
    "withdrawn",  # enrollment withdrawn mid-term
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
