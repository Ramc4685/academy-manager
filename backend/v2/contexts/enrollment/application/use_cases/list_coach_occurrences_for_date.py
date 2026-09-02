"""Query: dated occurrences assigned to a coach."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

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
    timezone: str | None = None
    start_at: datetime
    end_at: datetime
    # Primary coach of the roster session, so a supervisor's academy-wide
    # list can say whose class each row is. None when the session is gone.
    coach_id: str | None = None


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

        return await self._narrow(occurrences, on_date)

    async def execute_for_academy(self, on_date: date) -> list[CoachOccurrenceForDate]:
        """Every occurrence in the academy on ``on_date`` (coach supervisors)."""
        occurrences = await self._occurrences.list_on_date(on_date=on_date)
        return await self._narrow(occurrences, on_date)

    async def _narrow(
        self, occurrences: Sequence[SessionOccurrence], on_date: date
    ) -> list[CoachOccurrenceForDate]:
        rows = await _hydrate_occurrences(occurrences, sessions=self._sessions)
        # The repository returns a widened UTC candidate window (#510); keep
        # only occurrences that fall on ``on_date`` in the session's own
        # timezone so evening classes stay on their local calendar day.
        return [row for row in rows if _local_date(row.start_at, row.timezone) == on_date]


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

    async def execute_for_academy(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[CoachOccurrenceForDate]:
        """Upcoming occurrences across the academy (coach supervisors)."""
        occurrences = await self._occurrences.list_upcoming(now=now, limit=limit)
        return await _hydrate_occurrences(occurrences, sessions=self._sessions)


def _local_date(start_at: datetime, timezone_name: str | None) -> date:
    """Calendar date of ``start_at`` in the session's timezone.

    Naive datetimes (Mongo round-trips drop tzinfo) are treated as UTC
    instants. Sessions without a timezone fall back to UTC, preserving the
    pre-#510 behavior for fixtures that never set one.
    """
    instant = start_at if start_at.tzinfo is not None else start_at.replace(tzinfo=UTC)
    if not timezone_name:
        return instant.astimezone(UTC).date()
    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        return instant.astimezone(UTC).date()
    return instant.astimezone(tz).date()


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
                timezone=session.timezone if session else None,
                start_at=occurrence.start_at,
                end_at=occurrence.end_at,
                coach_id=getattr(session, "coach_id", None) if session else None,
            )
        )
    return rows
