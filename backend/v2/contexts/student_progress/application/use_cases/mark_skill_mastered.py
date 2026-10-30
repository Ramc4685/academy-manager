"""Use case: coach taps the students who mastered a skill in class.

One tap records a 1-of-1 test attempt (so the pass keeps the same audit
trail, events and level-completion check as the detailed test flow) and,
when it was the last required skill of the level, queues the level-up as a
recommendation. ``AutoApproveLevelUps`` lands it that evening; until then
``UnmarkSkillMastered`` takes it back.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.domain.errors import ActiveRecommendationExists

MASTERED_NOTE = "Marked as mastered in class"

MasteredOutcomeKind = Literal["mastered", "already_mastered", "not_on_level", "not_placed"]


class MarkSkillMasteredCommand(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    program_id: str
    student_ids: list[str]
    coach_id: str
    session_id: str | None = None


class MasteredOutcome(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    outcome: MasteredOutcomeKind
    level_up_queued: bool = False


class MarkSkillMastered:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        record_test_attempt: RecordTestAttempt,
        recommend_level_up: RecommendLevelUp,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._record = record_test_attempt
        self._recommend = recommend_level_up

    async def execute(self, cmd: MarkSkillMasteredCommand) -> list[MasteredOutcome]:
        skill = await self._skill_lookup.get_skill(cmd.skill_id)
        skill_level_id = getattr(skill, "level_id", None)
        outcomes: list[MasteredOutcome] = []
        for student_id in dict.fromkeys(cmd.student_ids):
            outcomes.append(await self._mark_one(cmd, student_id, skill_level_id))
        return outcomes

    async def _mark_one(
        self, cmd: MarkSkillMasteredCommand, student_id: str, skill_level_id: str | None
    ) -> MasteredOutcome:
        active = await self._level_progress.get_active(student_id, cmd.program_id)
        if active is None:
            return MasteredOutcome(student_id=student_id, outcome="not_placed")
        # Only the active level's skills count toward moving up; a skill from
        # another level would never complete anything.
        if skill_level_id != active.level_id:
            return MasteredOutcome(student_id=student_id, outcome="not_on_level")
        existing = await self._skill_progress.get(student_id, cmd.skill_id)
        if existing is not None and existing.status == "PASSED":
            return MasteredOutcome(student_id=student_id, outcome="already_mastered")

        result = await self._record.execute(
            RecordTestAttemptCommand(
                student_id=student_id,
                skill_id=cmd.skill_id,
                level_id=active.level_id,
                program_id=cmd.program_id,
                coach_id=cmd.coach_id,
                session_id=cmd.session_id,
                scoring_type="COACH_APPROVAL",
                attempts_count=1,
                success_count=1,
                notes=MASTERED_NOTE,
            )
        )
        queued = False
        if result.level_completed:
            try:
                await self._recommend.execute(
                    RecommendLevelUpCommand(
                        student_id=student_id,
                        program_id=cmd.program_id,
                        recommended_by=cmd.coach_id,
                    )
                )
                queued = True
            except ActiveRecommendationExists:
                queued = True
        return MasteredOutcome(student_id=student_id, outcome="mastered", level_up_queued=queued)
