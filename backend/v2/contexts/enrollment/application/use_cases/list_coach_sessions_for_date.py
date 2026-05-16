"""Query: sessions assigned to a coach on a date."""

from __future__ import annotations

from datetime import date

from backend.v2.contexts.enrollment.application.ports import SessionQuery
from backend.v2.contexts.enrollment.domain.models import Session


class ListCoachSessionsForDate:
    def __init__(self, sessions: SessionQuery) -> None:
        self._sessions = sessions

    async def execute(self, coach_id: str, on_date: date) -> list[Session]:
        return await self._sessions.for_coach_on_date(coach_id, on_date)
