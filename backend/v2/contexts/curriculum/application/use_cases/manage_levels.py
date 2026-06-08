"""Curriculum use cases: level management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.ports import LevelRepository, ProgramRepository
from backend.v2.contexts.curriculum.domain.errors import LevelNotFound, ProgramNotFound
from backend.v2.contexts.curriculum.domain.models import Level, LevelCompletionRule
from backend.v2.shared.ids import new_ulid


class CreateLevelCommand(BaseModel):
    model_config = {"frozen": True}
    program_id: str
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    completion_rule: LevelCompletionRule = "ALL_REQUIRED_SKILLS"
    requires_coach_recommendation: bool = True
    requires_admin_approval: bool = False
    created_by: str


class UpdateLevelCommand(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    name: str | None = None
    description: str | None = None
    completion_rule: LevelCompletionRule | None = None
    requires_coach_recommendation: bool | None = None
    requires_admin_approval: bool | None = None
    updated_by: str


class CreateLevel:
    def __init__(self, *, programs: ProgramRepository, levels: LevelRepository) -> None:
        self._programs = programs
        self._levels = levels

    async def execute(self, cmd: CreateLevelCommand) -> Level:
        program = await self._programs.get(cmd.program_id)
        if program is None:
            raise ProgramNotFound("program not found", program_id=cmd.program_id)
        now = datetime.now(UTC)
        level = Level(
            level_id=str(new_ulid()),
            program_id=cmd.program_id,
            academy_id="",  # injected by repo
            sequence=cmd.sequence,
            name=cmd.name,
            description=cmd.description,
            completion_rule=cmd.completion_rule,
            requires_coach_recommendation=cmd.requires_coach_recommendation,
            requires_admin_approval=cmd.requires_admin_approval,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=cmd.created_by,
        )
        await self._levels.save(level)
        return level


class UpdateLevel:
    def __init__(self, *, levels: LevelRepository) -> None:
        self._levels = levels

    async def execute(self, cmd: UpdateLevelCommand) -> Level:
        existing = await self._levels.get(cmd.level_id)
        if existing is None:
            raise LevelNotFound("level not found", level_id=cmd.level_id)
        updated = existing.model_copy(
            update={
                k: v
                for k, v in {
                    "name": cmd.name,
                    "description": cmd.description,
                    "completion_rule": cmd.completion_rule,
                    "requires_coach_recommendation": cmd.requires_coach_recommendation,
                    "requires_admin_approval": cmd.requires_admin_approval,
                    "updated_at": datetime.now(UTC),
                }.items()
                if v is not None
            }
        )
        await self._levels.update(updated)
        return updated


class ListLevels:
    def __init__(self, *, levels: LevelRepository) -> None:
        self._levels = levels

    async def execute(self, program_id: str) -> list[Level]:
        return await self._levels.list_for_program(program_id)
