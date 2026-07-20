"""Use case: coach recommends a student for level-up."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    ActiveRecommendationExists,
    LevelNotConfigured,
    LevelUpNotReady,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.domain.events import (
    LevelUpRecommended,
    LevelUpRecommendedPayload,
)
from backend.v2.contexts.student_progress.domain.logic import check_level_completion
from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id


def _resolve_academy_id() -> str:
    return current_academy_id()


class RecommendLevelUpCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    program_id: str
    recommended_by: str


class RecommendLevelUp:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recommendations = recommendations
        self._skill_lookup = skill_lookup
        self._outbox = outbox

    async def execute(self, cmd: RecommendLevelUpCommand) -> LevelUpRecommendation:
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level",
                student_id=cmd.student_id,
                program_id=cmd.program_id,
            )

        # Check all required skills are passed
        all_skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        required_ids = [s.skill_id for s in all_skills if getattr(s, "is_required", True)]
        passed_records = await self._skill_progress.list_passed_for_student_level(
            cmd.student_id, active.level_id
        )
        passed_ids = {sp.skill_id for sp in passed_records}
        if not check_level_completion(required_ids, passed_ids):
            raise LevelUpNotReady(
                "not all required skills are passed",
                student_id=cmd.student_id,
                level_id=active.level_id,
            )

        # Check no active recommendation exists
        existing_rec = await self._recommendations.get_active_for_student(
            cmd.student_id, cmd.program_id
        )
        if existing_rec is not None:
            raise ActiveRecommendationExists(
                "an active level-up recommendation already exists",
                student_id=cmd.student_id,
                rec_id=existing_rec.rec_id,
            )

        # Find the next level
        current_level = await self._skill_lookup.get_level(active.level_id)
        if current_level is None:
            raise LevelNotConfigured("current level not found", level_id=active.level_id)
        next_level = await self._skill_lookup.get_next_level(
            cmd.program_id, getattr(current_level, "sequence", 0)
        )
        to_level_id = next_level.level_id if next_level else active.level_id  # type: ignore[attr-defined]

        now = datetime.now(UTC)
        rec = LevelUpRecommendation(
            rec_id=str(new_ulid()),
            academy_id="",
            student_id=cmd.student_id,
            from_level_id=active.level_id,
            to_level_id=to_level_id,
            program_id=cmd.program_id,
            status="RECOMMENDED",
            recommended_by=cmd.recommended_by,
            recommended_at=now,
        )
        await self._recommendations.save(rec)
        if self._outbox is not None:
            await self._outbox.append(
                LevelUpRecommended(
                    aggregate_id=rec.rec_id,
                    academy_id=_resolve_academy_id(),
                    payload=LevelUpRecommendedPayload(
                        student_id=rec.student_id,
                        from_level_id=rec.from_level_id,
                        to_level_id=rec.to_level_id,
                        program_id=rec.program_id,
                        rec_id=rec.rec_id,
                        recommended_by=rec.recommended_by,
                    ),
                )
            )
        return rec
