"""Enrollment application ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

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

    async def update_status(self, enrollment_id: str, status: str) -> None: ...

    async def update_session(self, enrollment_id: str, session_id: str) -> None: ...

    async def update_amount_cents(self, enrollment_id: str, amount_cents: int | None) -> None: ...

    async def get(self, enrollment_id: str) -> Enrollment | None: ...

    async def find_for_session_student(
        self, session_id: str, student_id: str
    ) -> Enrollment | None: ...


class StudentWriter(Protocol):
    async def upsert(self, student: Student) -> None: ...


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
