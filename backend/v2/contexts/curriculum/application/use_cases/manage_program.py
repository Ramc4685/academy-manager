"""Curriculum use cases: program management."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.curriculum.application.ports import ProgramRepository
from backend.v2.contexts.curriculum.domain.models import Program
from backend.v2.shared.ids import new_ulid


class CreateProgramCommand(BaseModel):
    model_config = {"frozen": True}
    sport: str
    name: str
    description: str = ""
    created_by: str


class CreateProgram:
    def __init__(self, *, programs: ProgramRepository) -> None:
        self._programs = programs

    async def execute(self, cmd: CreateProgramCommand) -> Program:
        now = datetime.now(UTC)
        program = Program(
            program_id=str(new_ulid()),
            academy_id="",  # injected by repo via tenant context
            sport=cmd.sport,
            name=cmd.name,
            description=cmd.description,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=cmd.created_by,
        )
        await self._programs.save(program)
        return program


class ListPrograms:
    def __init__(self, *, programs: ProgramRepository) -> None:
        self._programs = programs

    async def execute(self) -> list[Program]:
        return await self._programs.list_active()


class GetProgram:
    def __init__(self, *, programs: ProgramRepository) -> None:
        self._programs = programs

    async def execute(self, program_id: str) -> Program | None:
        return await self._programs.get(program_id)
