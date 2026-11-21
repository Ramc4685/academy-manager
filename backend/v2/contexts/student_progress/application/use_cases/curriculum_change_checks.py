"""Use case: what a curriculum edit (retire, reorder) does to students on it.

The curriculum context owns levels and skills; these checks run in the admin
route around a curriculum edit, so retiring a level never strands students
and retiring a skill lets students it was holding back move on.
"""

from __future__ import annotations

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
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
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        recommendations: LevelUpRecommendationRepository,
        recommend_level_up: RecommendLevelUp,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._recs = recommendations
        self._recommend = recommend_level_up

    async def active_student_ids(self, level_id: str) -> list[str]:
        """Students whose current level this is."""
        return [p.student_id for p in await self._level_progress.list_active_for_level(level_id)]

    async def has_pending_level_ups(self, program_id: str) -> bool:
        """A queued level-up names its target level; renumbering would move it."""
        return any(rec.program_id == program_id for rec in await self._recs.list_pending())

    async def pending_level_ups_into(self, level_id: str) -> int:
        """Queued level-ups that would place students on ``level_id``."""
        return sum(rec.to_level_id == level_id for rec in await self._recs.list_pending())

    async def held_back_by(self, skill_id: str) -> list[str]:
        """Before a skill is retired: students on its level who have not passed it.

        Only they can be freed by the retire. Nobody when the skill is already
        retired or not required, so a repeat retire or an optional skill never
        re-queues a level-up the owner already rejected.
        """
        skill = await self._skill_lookup.get_skill(skill_id)
        if (
            skill is None
            or not getattr(skill, "is_active", True)
            or not getattr(skill, "is_required", True)
        ):
            return []
        level_id = str(getattr(skill, "level_id", ""))
        on_level = await self.active_student_ids(level_id)
        passed = {
            row.student_id
            for row in await self._skill_progress.list_for_students(on_level, level_id)
            if row.skill_id == skill_id and row.status == "PASSED"
        }
        return [sid for sid in on_level if sid not in passed]

    async def recheck_students(self, level_id: str, student_ids: list[str], actor: str) -> int:
        """After the retire: queue the level-up for those students only."""
        wanted = set(student_ids)
        queued = 0
        for progress in await self._level_progress.list_active_for_level(level_id):
            if progress.student_id not in wanted:
                continue
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
