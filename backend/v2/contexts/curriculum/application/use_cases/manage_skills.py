"""Curriculum use cases: skill management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.ports import LevelRepository, SkillRepository
from backend.v2.contexts.curriculum.domain.errors import InvalidOrder, LevelNotFound, SkillNotFound
from backend.v2.contexts.curriculum.domain.models import (
    MAX_PASS_TRIES as MAX_PASS_TRIES,  # re-exported for interfaces
)
from backend.v2.contexts.curriculum.domain.models import (
    MIN_PASS_TRIES as MIN_PASS_TRIES,
)
from backend.v2.contexts.curriculum.domain.models import (
    PassRule as PassRule,
)
from backend.v2.contexts.curriculum.domain.models import (
    ScoringType as ScoringType,  # re-exported for interfaces
)
from backend.v2.contexts.curriculum.domain.models import (
    Skill,
)
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
    pass_rule: PassRule = "ONE_TAP"
    pass_tries: int | None = Field(default=None, ge=MIN_PASS_TRIES, le=MAX_PASS_TRIES)
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
    pass_rule: PassRule | None = None
    pass_tries: int | None = Field(default=None, ge=MIN_PASS_TRIES, le=MAX_PASS_TRIES)
    #: False retires the skill; it stops counting toward the level.
    is_active: bool | None = None
    updated_by: str


class CreateSkill:
    def __init__(self, *, levels: LevelRepository, skills: SkillRepository) -> None:
        self._levels = levels
        self._skills = skills

    async def execute(self, cmd: CreateSkillCommand) -> Skill:
        level = await self._levels.get(cmd.level_id)
        if level is None or level.program_id != cmd.program_id:
            raise LevelNotFound(
                "level not found in this program",
                level_id=cmd.level_id,
                program_id=cmd.program_id,
            )
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
            pass_rule=cmd.pass_rule,
            pass_tries=cmd.pass_tries,
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
                "pass_rule": cmd.pass_rule,
                "pass_tries": cmd.pass_tries,
                "is_active": cmd.is_active,
                "updated_at": datetime.now(UTC),
            }.items()
            if v is not None
        }
        # Re-validate, not model_copy: field bounds and the rule/tries pairing
        # must hold on the merged skill.
        updated = Skill.model_validate({**existing.model_dump(), **updates})
        await self._skills.update(updated)
        return updated


class ListSkills:
    def __init__(self, *, skills: SkillRepository) -> None:
        self._skills = skills

    async def execute(self, level_id: str) -> list[Skill]:
        return await self._skills.list_for_level(level_id)


class ReorderSkills:
    """Renumber a level's active skills in the given order; retired ones follow."""

    def __init__(self, *, skills: SkillRepository) -> None:
        self._skills = skills

    async def execute(self, level_id: str, skill_ids: list[str]) -> list[str]:
        everything = await self._skills.list_all_for_level(level_id)
        active = [s.skill_id for s in everything if s.is_active]
        if len(set(skill_ids)) != len(skill_ids) or set(skill_ids) != set(active):
            raise InvalidOrder(
                "list every active skill of the level exactly once", level_id=level_id
            )
        ordered = skill_ids + [s.skill_id for s in everything if not s.is_active]
        await self._skills.resequence(ordered)
        return ordered
