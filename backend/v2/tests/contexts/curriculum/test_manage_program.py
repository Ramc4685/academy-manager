"""Tests for curriculum program management use cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    CreateProgram,
    CreateProgramCommand,
    ResolveDefaultActiveProgram,
)
from backend.v2.contexts.curriculum.domain.errors import (
    ActiveProgramExists,
    MultipleActivePrograms,
    NoActiveProgram,
)
from backend.v2.contexts.curriculum.domain.models import Program

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 6, tzinfo=UTC)


class _ProgramRepo:
    def __init__(self, programs: list[Program]) -> None:
        self._programs = programs

    async def list_active(self) -> list[Program]:
        return [program for program in self._programs if program.is_active]

    async def save(self, program: Program) -> None:
        self._programs.append(program)


def _program(program_id: str, *, is_active: bool = True) -> Program:
    return Program(
        program_id=program_id,
        academy_id="academy-1",
        sport="badminton",
        name=f"Program {program_id}",
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
        created_by="admin-1",
    )


async def test_resolve_default_active_program_returns_only_active_program() -> None:
    resolver = ResolveDefaultActiveProgram(
        programs=_ProgramRepo([_program("inactive", is_active=False), _program("program-1")])
    )

    result = await resolver.execute()

    assert result.program_id == "program-1"


async def test_resolve_default_active_program_rejects_no_active_programs() -> None:
    resolver = ResolveDefaultActiveProgram(
        programs=_ProgramRepo([_program("inactive", is_active=False)])
    )

    with pytest.raises(NoActiveProgram):
        await resolver.execute()


async def test_resolve_default_active_program_requires_explicit_selection_for_multiple_programs() -> (
    None
):
    resolver = ResolveDefaultActiveProgram(
        programs=_ProgramRepo([_program("program-1"), _program("program-2")])
    )

    with pytest.raises(MultipleActivePrograms):
        await resolver.execute()


_CREATE = CreateProgramCommand(sport="badminton", name="Juniors", created_by="admin-1")


async def test_create_program_refuses_a_second_active_program() -> None:
    repo = _ProgramRepo([_program("program-1")])

    with pytest.raises(ActiveProgramExists) as exc_info:
        await CreateProgram(programs=repo).execute(_CREATE)

    assert exc_info.value.details == {"program_id": "program-1"}
    assert [p.program_id for p in await repo.list_active()] == ["program-1"]
    # The single-program resolver the coach/student surfaces use still works.
    assert (await ResolveDefaultActiveProgram(programs=repo).execute()).program_id == "program-1"


async def test_create_program_allowed_when_only_inactive_programs_exist() -> None:
    repo = _ProgramRepo([_program("old", is_active=False)])

    created = await CreateProgram(programs=repo).execute(_CREATE)

    assert [p.program_id for p in await repo.list_active()] == [created.program_id]
