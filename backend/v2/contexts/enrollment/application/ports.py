"""Enrollment application ports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

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
    async def get(self, session_id: str) -> Session | None: ...


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...

    async def list_for_session_between(
        self,
        *,
        session_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[SessionOccurrence]: ...

    async def save_many(self, occurrences: list[SessionOccurrence]) -> None: ...


class EnrollmentQuery(Protocol):
    async def active_for_session(self, session_id: str) -> list[Enrollment]: ...
    async def is_active(self, session_id: str, student_id: str) -> bool: ...


class StudentQuery(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class RosterQuery(Protocol):
    """Composed read of roster for a session."""

    async def for_session(self, session_id: str) -> list[RosterEntry]: ...


# --- Write-side ports (Wave 2+) ---


class SessionWriter(Protocol):
    async def try_reserve_seat(self, session_id: str) -> bool:
        """Atomic capacity check + reserve. Returns False if at capacity."""

    async def release_seat(self, session_id: str) -> None: ...

    async def update_status(self, session_id: str, status: str) -> None: ...

    async def create(self, session: Session) -> None: ...

    async def update(self, session: Session) -> None: ...


class EnrollmentWriter(Protocol):
    async def create(self, enrollment: Enrollment) -> None: ...

    async def update_status(self, enrollment_id: str, status: str) -> None: ...

    async def update_session(self, enrollment_id: str, session_id: str) -> None: ...

    async def get(self, enrollment_id: str) -> Enrollment | None: ...


class StudentWriter(Protocol):
    async def upsert(self, student: Student) -> None: ...


class WaitlistRepository(Protocol):
    async def add(self, entry: WaitlistEntry) -> None: ...

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None: ...

    async def update_status(self, waitlist_id: str, status: str) -> None: ...
