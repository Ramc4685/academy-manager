"""Adapters wiring Coaching's lookup ports to Enrollment's queries.

Coaching never imports Enrollment directly (ADR-0005 rule 5). The
composition root supplies these adapters at wire time. Both contexts'
ports define independent shapes; the adapter is the only place that knows
about both.
"""

from __future__ import annotations

from datetime import date

from backend.v2.contexts.coaching.application.ports import EnrollmentLookup, SessionLookup
from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    SessionQuery,
)


class EnrollmentSessionLookup(SessionLookup):
    """Implements Coaching's SessionLookup using Enrollment's SessionQuery."""

    def __init__(self, sessions: SessionQuery) -> None:
        self._sessions = sessions

    async def is_coach_assigned(self, coach_id: str, session_id: str, on_date: date) -> bool:
        sessions = await self._sessions.for_coach_on_date(coach_id, on_date)
        return any(s.session_id == session_id for s in sessions)

    async def is_cancelled(self, session_id: str) -> bool:
        s = await self._sessions.get(session_id)
        return s is not None and s.status == "cancelled"

    async def session_date(self, session_id: str) -> date | None:
        s = await self._sessions.get(session_id)
        return s.start_at.date() if s else None


class EnrollmentLookupAdapter(EnrollmentLookup):
    """Implements Coaching's EnrollmentLookup using Enrollment's EnrollmentQuery."""

    def __init__(self, enrollments: EnrollmentQuery) -> None:
        self._enrollments = enrollments

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return await self._enrollments.is_active(session_id, student_id)
