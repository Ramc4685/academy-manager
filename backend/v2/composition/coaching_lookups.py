"""Adapters wiring Coaching's lookup ports to Enrollment's queries.

Coaching never imports Enrollment directly (ADR-0005 rule 5). The
composition root supplies these adapters at wire time. Both contexts'
ports define independent shapes; the adapter is the only place that knows
about both.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.v2.contexts.coaching.application.ports import (
    EnrollmentLookup,
    OccurrenceDetails,
    OccurrenceLookup,
    SessionLookup,
)
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


class EnrollmentOccurrenceLookup(OccurrenceLookup):
    """Maps Enrollment-owned occurrences into Coaching's occurrence port."""

    def __init__(self, occurrences: Any) -> None:
        self._occurrences = occurrences

    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        occurrence = await self._occurrences.get(occurrence_id)
        if occurrence is None:
            return None
        return OccurrenceDetails(
            occurrence_id=occurrence.occurrence_id,
            session_id=occurrence.session_id,
            starts_at=occurrence.start_at,
            status=occurrence.status,
            scheduled_coach_id=occurrence.scheduled_coach_id,
            actual_coach_id=occurrence.actual_coach_id,
            substitute_coach_id=occurrence.substitute_coach_id,
            template_session_id=occurrence.template_session_id,
            assistant_coach_ids=occurrence.assistant_coach_ids,
        )
