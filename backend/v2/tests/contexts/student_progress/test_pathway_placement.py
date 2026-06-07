"""Tests for canonical student pathway placement read model."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_pathway_placement import (
    GetStudentPathwayPlacement,
    StudentPathwayPlacementRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    StudentLevelProgress,
    StudentSkillProgress,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 6, tzinfo=UTC)


class _LevelProgressRepo:
    def __init__(self, active: StudentLevelProgress | None) -> None:
        self._active = active

    async def get_active(self, student_id: str, program_id: str):
        return self._active


class _SkillProgressRepo:
    def __init__(self, rows: list[StudentSkillProgress]) -> None:
        self._rows = rows

    async def list_for_student_level(self, student_id: str, level_id: str):
        return [
            row for row in self._rows if row.student_id == student_id and row.level_id == level_id
        ]


class _SkillLookup:
    def __init__(self, *, level: object | None, skills: list[object]) -> None:
        self._level = level
        self._skills = skills

    async def get_level(self, level_id: str):
        return self._level

    async def list_skills_for_level(self, level_id: str):
        return self._skills


def _request() -> StudentPathwayPlacementRequest:
    return StudentPathwayPlacementRequest(student_id="student-1", program_id="program-1")


def _active(level_id: str = "level-1") -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id="progress-1",
        academy_id="academy-1",
        student_id="student-1",
        program_id="program-1",
        level_id=level_id,
        started_at=NOW,
        created_at=NOW,
    )


def _skill(skill_id: str) -> object:
    return SimpleNamespace(skill_id=skill_id)


def _skill_progress(skill_id: str, status: str) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"progress-{skill_id}",
        academy_id="academy-1",
        student_id="student-1",
        skill_id=skill_id,
        level_id="level-1",
        program_id="program-1",
        status=status,
        last_updated_at=NOW,
        last_updated_by="coach-1",
    )


async def test_pathway_placement_returns_level_metadata_and_skill_summary() -> None:
    use_case = GetStudentPathwayPlacement(
        level_progress=_LevelProgressRepo(_active()),
        skill_progress=_SkillProgressRepo(
            [
                _skill_progress("skill-1", "PASSED"),
                _skill_progress("skill-2", "TEST_READY"),
                _skill_progress("skill-3", "NOT_STARTED"),
            ]
        ),
        skill_lookup=_SkillLookup(
            level=SimpleNamespace(level_id="level-1", sequence=2, name="Rally Builder"),
            skills=[_skill("skill-1"), _skill("skill-2"), _skill("skill-3")],
        ),
    )

    result = await use_case.execute(_request())

    assert result.student_id == "student-1"
    assert result.program_id == "program-1"
    assert result.level_id == "level-1"
    assert result.level_sequence == 2
    assert result.level_name == "Rally Builder"
    assert result.placement_status == "active"
    assert result.next_action == "record_tests"
    assert result.skills_total == 3
    assert result.skills_completed == 1
    assert result.skills_ready_for_test == 1
    assert result.completion_percentage == 33


async def test_pathway_placement_returns_placement_needed_when_student_is_unplaced() -> None:
    use_case = GetStudentPathwayPlacement(
        level_progress=_LevelProgressRepo(None),
        skill_progress=_SkillProgressRepo([]),
        skill_lookup=_SkillLookup(level=None, skills=[]),
    )

    result = await use_case.execute(_request())

    assert result.student_id == "student-1"
    assert result.program_id == "program-1"
    assert result.level_id is None
    assert result.level_name is None
    assert result.placement_status == "unplaced"
    assert result.next_action == "place_in_level"
    assert result.skills_total == 0
    assert result.completion_percentage == 0
