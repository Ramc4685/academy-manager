"""Curriculum use cases: criteria management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.ports import CriterionRepository, SkillRepository
from backend.v2.contexts.curriculum.domain.errors import SkillNotFound
from backend.v2.contexts.curriculum.domain.models import SkillCriterion
from backend.v2.shared.ids import new_ulid


class AddSkillCriterionCommand(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    level_id: str
    program_id: str
    description: str
    display_order: int = Field(ge=0, default=0)
    created_by: str


class AddSkillCriterion:
    def __init__(self, *, skills: SkillRepository, criteria: CriterionRepository) -> None:
        self._skills = skills
        self._criteria = criteria

    async def execute(self, cmd: AddSkillCriterionCommand) -> SkillCriterion:
        skill = await self._skills.get(cmd.skill_id)
        if skill is None:
            raise SkillNotFound("skill not found", skill_id=cmd.skill_id)
        criterion = SkillCriterion(
            criterion_id=str(new_ulid()),
            skill_id=cmd.skill_id,
            level_id=cmd.level_id,
            program_id=cmd.program_id,
            academy_id="",  # injected by repo
            description=cmd.description,
            display_order=cmd.display_order,
            created_at=datetime.now(UTC),
            created_by=cmd.created_by,
        )
        await self._criteria.save(criterion)
        return criterion
