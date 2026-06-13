"""Use-case tests for parent-safe recent skill updates."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_recent_skill_updates import (
    GetInProgressSkills,
    GetRecentSkillUpdates,
)
from backend.v2.contexts.student_progress.domain.models import StudentSkillProgress

pytestmark = pytest.mark.asyncio

ACADEMY_ID = "academy-1"
STUDENT_ID = "student-1"
PROGRAM_ID = "program-1"
LEVEL_ID = "level-1"


def _progress(skill_id: str, status: str, updated_at: datetime) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{skill_id}",
        academy_id=ACADEMY_ID,
        student_id=STUDENT_ID,
        skill_id=skill_id,
        level_id=LEVEL_ID,
        program_id=PROGRAM_ID,
        status=status,  # type: ignore[arg-type]
        last_updated_at=updated_at,
        last_updated_by="coach-1",
    )


class _SkillProgressRepo:
    def __init__(self, rows: list[StudentSkillProgress]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int]] = []
        self.in_progress_calls: list[str] = []

    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]:
        self.calls.append((student_id, limit))
        return self.rows[:limit]

    async def list_in_progress_for_student(self, student_id: str) -> list[StudentSkillProgress]:
        self.in_progress_calls.append(student_id)
        return [
            row
            for row in self.rows
            if row.status in {"INTRODUCED", "LEARNING", "PRACTICING", "TEST_READY", "NEEDS_REVIEW"}
        ]


class _SkillLookup:
    async def get_skill(self, skill_id: str) -> object | None:
        names = {
            "skill-new": "Ready stance",
            "skill-old": "Forehand grip",
        }
        return SimpleNamespace(skill_id=skill_id, name=names[skill_id])


async def test_recent_skill_updates_are_ordered_and_parent_safe() -> None:
    newer = datetime(2026, 6, 13, 15, 0, tzinfo=UTC)
    older = datetime(2026, 6, 12, 15, 0, tzinfo=UTC)
    repo = _SkillProgressRepo(
        [
            _progress("skill-old", "PRACTICING", older),
            _progress("skill-new", "TEST_READY", newer),
        ]
    )

    result = await GetRecentSkillUpdates(
        skill_progress=repo,
        skill_lookup=_SkillLookup(),
    ).execute(STUDENT_ID)

    assert [row.skill_id for row in result] == ["skill-new", "skill-old"]
    assert result[0].skill_name == "Ready stance"
    assert result[0].status == "TEST_READY"
    assert result[0].updated_at == newer
    assert repo.calls == [(STUDENT_ID, 10)]

    dumped = result[0].model_dump(mode="json")
    assert set(dumped) == {"skill_id", "skill_name", "status", "updated_at"}
    assert "teaching_points" not in dumped
    assert "safety_notes" not in dumped
    assert "goal_summary" not in dumped


async def test_in_progress_skills_are_not_limited_to_recent_window() -> None:
    rows = [
        _progress(
            f"recent-passed-{idx}",
            "PASSED",
            datetime(2026, 6, 13, 15, idx, tzinfo=UTC),
        )
        for idx in range(10)
    ]
    older = datetime(2026, 5, 30, 15, 0, tzinfo=UTC)
    rows.append(_progress("skill-old", "PRACTICING", older))
    repo = _SkillProgressRepo(rows)

    result = await GetInProgressSkills(
        skill_progress=repo,
        skill_lookup=_SkillLookup(),
    ).execute(STUDENT_ID)

    assert [row.skill_id for row in result] == ["skill-old"]
    assert result[0].skill_name == "Forehand grip"
    assert result[0].status == "PRACTICING"
    assert result[0].updated_at == older
    assert repo.calls == []
    assert repo.in_progress_calls == [STUDENT_ID]
