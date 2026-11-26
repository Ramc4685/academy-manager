"""Use-case tests for GetActiveLevelNames (fake repos, no Mongo)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_active_level_names import (
    GetActiveLevelNames,
)
from backend.v2.contexts.student_progress.domain.models import StudentLevelProgress

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def _active(student_id: str, level_id: str) -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=f"lp-{student_id}",
        academy_id="test-academy",
        student_id=student_id,
        program_id="prog",
        level_id=level_id,
        status="active",
        started_at=NOW,
        created_at=NOW,
    )


class _LevelProgress:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self.rows = rows
        self.calls = 0

    async def list_active_for_students(self, student_ids, program_id):
        self.calls += 1
        return [r for r in self.rows if r.student_id in student_ids and r.program_id == program_id]


class _Levels:
    def __init__(self) -> None:
        self.reads: list[str] = []

    async def get_level(self, level_id):
        self.reads.append(level_id)
        return {"l1": SimpleNamespace(name="Grip & Control")}.get(level_id)


@pytest.mark.asyncio
async def test_names_each_placed_student_and_leaves_out_the_unplaced() -> None:
    levels = _Levels()
    use_case = GetActiveLevelNames(
        level_progress=_LevelProgress(
            [_active("a", "l1"), _active("b", "l1"), _active("c", "gone")]
        ),
        skill_lookup=levels,
    )

    names = await use_case.execute(["a", "b", "c", "unplaced"], "prog")

    assert names == {"a": "Grip & Control", "b": "Grip & Control"}
    assert sorted(levels.reads) == ["gone", "l1"]  # one read per level, not per child


@pytest.mark.asyncio
async def test_no_students_reads_nothing() -> None:
    progress = _LevelProgress([])
    assert (
        await GetActiveLevelNames(level_progress=progress, skill_lookup=_Levels()).execute(
            [], "prog"
        )
        == {}
    )
    assert progress.calls == 0
