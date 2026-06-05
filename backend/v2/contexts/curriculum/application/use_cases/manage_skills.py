"""Curriculum use cases: skill management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.ports import LevelRepository, SkillRepository
from backend.v2.contexts.curriculum.domain.errors import LevelNotFound, SkillNotFound
from backend.v2.contexts.curriculum.domain.models import ScoringType, Skill
from backend.v2.shared.ids import new_ulid


class CreateSkillCommand(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    program_id: str
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    is_required: bool = True
    scoring_type: ScoringType = "ATTEMPT_BASED"
    pass_threshold_pct: float = Field(default=70.0, ge=0.0, le=100.0)
    coach_override_allowed: bool = False
    created_by: str


class UpdateSkillCommand(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    name: str | None = None
    description: str | None = None
    is_required: bool | None = None
    scoring_type: ScoringType | None = None
    pass_threshold_pct: float | None = None
    coach_override_allowed: bool | None = None
    updated_by: str


class CreateSkill:
    def __init__(self, *, levels: LevelRepository, skills: SkillRepository) -> None:
        self._levels = levels
        self._skills = skills

    async def execute(self, cmd: CreateSkillCommand) -> Skill:
        level = await self._levels.get(cmd.level_id)
        if level is None:
            raise LevelNotFound("level not found", level_id=cmd.level_id)
        now = datetime.now(UTC)
        skill = Skill(
            skill_id=str(new_ulid()),
            level_id=cmd.level_id,
            program_id=cmd.program_id,
            academy_id="",  # injected by repo
            sequence=cmd.sequence,
            name=cmd.name,
            description=cmd.description,
            is_required=cmd.is_required,
            scoring_type=cmd.scoring_type,
            pass_threshold_pct=cmd.pass_threshold_pct,
            coach_override_allowed=cmd.coach_override_allowed,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=cmd.created_by,
        )
        await self._skills.save(skill)
        return skill


class UpdateSkill:
    def __init__(self, *, skills: SkillRepository) -> None:
        self._skills = skills

    async def execute(self, cmd: UpdateSkillCommand) -> Skill:
        existing = await self._skills.get(cmd.skill_id)
        if existing is None:
            raise SkillNotFound("skill not found", skill_id=cmd.skill_id)
        updates = {
            k: v
            for k, v in {
                "name": cmd.name,
                "description": cmd.description,
                "is_required": cmd.is_required,
                "scoring_type": cmd.scoring_type,
                "pass_threshold_pct": cmd.pass_threshold_pct,
                "coach_override_allowed": cmd.coach_override_allowed,
                "updated_at": datetime.now(UTC),
            }.items()
            if v is not None
        }
        updated = existing.model_copy(update=updates)
        await self._skills.update(updated)
        return updated


class ListSkills:
    def __init__(self, *, skills: SkillRepository) -> None:
        self._skills = skills

    async def execute(self, level_id: str) -> list[Skill]:
        return await self._skills.list_for_level(level_id)
