"""Use case: what a curriculum edit (retire, reorder) does to students on it.

The curriculum context owns levels and skills; these checks run in the admin
route around a curriculum edit, so retiring a level never strands students
and retiring a skill lets students it was holding back move on.
"""

from __future__ import annotations

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    StudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.domain.errors import (
    ActiveRecommendationExists,
    EnrollmentEnded,
    LevelNotConfigured,
    LevelUpNotReady,
    StudentNotPlaced,
)


class CurriculumChangeChecks:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        recommend_level_up: RecommendLevelUp,
    ) -> None:
        self._level_progress = level_progress
        self._recs = recommendations
        self._recommend = recommend_level_up

    async def active_student_ids(self, level_id: str) -> list[str]:
        """Students whose current level this is."""
        return [p.student_id for p in await self._level_progress.list_active_for_level(level_id)]

    async def has_pending_level_ups(self, program_id: str) -> bool:
        """A queued level-up names its target level; renumbering would move it."""
        return any(rec.program_id == program_id for rec in await self._recs.list_pending())

    async def recheck_level(self, level_id: str, actor: str) -> int:
        """Queue the level-up for students a retired skill was holding back."""
        queued = 0
        for progress in await self._level_progress.list_active_for_level(level_id):
            try:
                await self._recommend.execute(
                    RecommendLevelUpCommand(
                        student_id=progress.student_id,
                        program_id=progress.program_id,
                        recommended_by=actor,
                    )
                )
            except (
                ActiveRecommendationExists,
                EnrollmentEnded,
                LevelNotConfigured,
                LevelUpNotReady,
                StudentNotPlaced,
            ):
                continue
            queued += 1
        return queued
