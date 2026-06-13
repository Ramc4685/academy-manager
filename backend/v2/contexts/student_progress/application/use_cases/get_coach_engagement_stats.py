"""Use case: aggregate coach-entered student progress outcomes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Protocol

from pydantic import BaseModel, Field


class CoachEngagementRow(BaseModel):
    coach_id: str
    outcomes_recorded: int = Field(ge=0)


class CoachEngagementStatsRepository(Protocol):
    async def count_updates_by_coach(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[object]: ...


class GetCoachEngagementStats:
    def __init__(self, skill_progress: CoachEngagementStatsRepository) -> None:
        self._skill_progress = skill_progress

    async def execute(self, *, start_date: date, end_date: date) -> list[CoachEngagementRow]:
        start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
        end_at = datetime.combine(end_date, time.max, tzinfo=UTC)
        rows = await self._skill_progress.count_updates_by_coach(
            start_at=start_at,
            end_at=end_at,
        )
        return [
            CoachEngagementRow(
                coach_id=str(_field(row, "coach_id")),
                outcomes_recorded=int(_field(row, "outcomes_recorded")),
            )
            for row in rows
        ]


def _field(row: object, name: str) -> object:
    if isinstance(row, dict):
        return row[name]
    return getattr(row, name)
