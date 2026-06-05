"""Use case: get the queue of students ready for level-up."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation


@dataclass(frozen=True)
class GetLevelUpQueueCommand:
    program_id: str | None = field(default=None)


class GetLevelUpQueue:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recs = recommendations
        self._skill_lookup = skill_lookup

    async def execute(self, cmd: GetLevelUpQueueCommand) -> list[LevelUpRecommendation]:
        pending = await self._recs.list_pending()
        if cmd.program_id is not None:
            pending = [rec for rec in pending if rec.program_id == cmd.program_id]
        return pending
