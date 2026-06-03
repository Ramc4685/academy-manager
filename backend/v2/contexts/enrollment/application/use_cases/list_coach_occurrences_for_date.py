"""Query: dated occurrences assigned to a coach."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    SessionOccurrenceRepository,
    SessionQuery,
)
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence


class CoachOccurrenceForDate(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    roster_session_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime


class ListCoachOccurrencesForDate:
    def __init__(
        self,
        *,
        occurrences: SessionOccurrenceRepository,
        sessions: SessionQuery,
    ) -> None:
        self._occurrences = occurrences
        self._sessions = sessions

    async def execute(self, coach_id: str, on_date: date) -> list[CoachOccurrenceForDate]:
        occurrences = await self._occurrences.list_for_coach_on_date(
            coach_id=coach_id,
            on_date=on_date,
        )

        return await _hydrate_occurrences(occurrences, sessions=self._sessions)


class ListCoachUpcomingOccurrences:
    def __init__(
        self,
        *,
        occurrences: SessionOccurrenceRepository,
        sessions: SessionQuery,
    ) -> None:
        self._occurrences = occurrences
        self._sessions = sessions

    async def execute(
        self,
        coach_id: str,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[CoachOccurrenceForDate]:
        occurrences = await self._occurrences.list_for_coach_upcoming(
            coach_id=coach_id,
            now=now,
            limit=limit,
        )
        return await _hydrate_occurrences(occurrences, sessions=self._sessions)


async def _hydrate_occurrences(
    occurrences: Sequence[SessionOccurrence],
    *,
    sessions: SessionQuery,
) -> list[CoachOccurrenceForDate]:
    rows: list[CoachOccurrenceForDate] = []
    for occurrence in occurrences:
        roster_session_id = occurrence.template_session_id or occurrence.session_id
        session = await sessions.get(roster_session_id)
        if session is None and occurrence.template_session_id:
            session = await sessions.get(occurrence.session_id)

        rows.append(
            CoachOccurrenceForDate(
                occurrence_id=occurrence.occurrence_id,
                session_id=roster_session_id,
                roster_session_id=roster_session_id,
                title=session.title if session else "Session",
                location=session.location if session else "",
                start_at=occurrence.start_at,
                end_at=occurrence.end_at,
            )
        )
    return rows
