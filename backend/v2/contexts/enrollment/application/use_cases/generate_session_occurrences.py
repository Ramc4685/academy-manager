"""Generate durable weekly occurrences for a recurring session."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, model_validator

from backend.v2.contexts.enrollment.application.ports import SessionOccurrenceRepository
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence


class GenerateSessionOccurrencesCommand(BaseModel):
    model_config = {"frozen": True}

    range_start: datetime
    range_end: datetime

    @model_validator(mode="after")
    def _valid_range(self) -> GenerateSessionOccurrencesCommand:
        if self.range_end < self.range_start:
            raise ValueError("range_end must be on or after range_start")
        return self


class GenerateSessionOccurrences:
    def __init__(self, occurrences: SessionOccurrenceRepository) -> None:
        self._occurrences = occurrences

    async def execute(
        self,
        *,
        session: Session,
        cmd: GenerateSessionOccurrencesCommand,
    ) -> list[SessionOccurrence]:
        candidates = _weekly_occurrences(session, cmd.range_start, cmd.range_end)
        await self._occurrences.save_many(candidates)
        return await self._occurrences.list_for_session_between(
            session_id=session.session_id,
            start_at=cmd.range_start,
            end_at=cmd.range_end,
        )


def _weekly_occurrences(
    session: Session,
    range_start: datetime,
    range_end: datetime,
) -> list[SessionOccurrence]:
    duration = session.end_at - session.start_at
    current = session.start_at
    while current < range_start:
        current += timedelta(days=7)

    rows: list[SessionOccurrence] = []
    while current <= range_end:
        rows.append(
            SessionOccurrence(
                occurrence_id=_occurrence_id(session.session_id, current),
                academy_id=session.academy_id,
                session_id=session.session_id,
                start_at=current,
                end_at=current + duration,
                status="scheduled",
                scheduled_coach_id=session.coach_id,
            )
        )
        current += timedelta(days=7)
    return rows


def _occurrence_id(session_id: str, start_at: datetime) -> str:
    return f"{session_id}:{start_at.isoformat()}"
