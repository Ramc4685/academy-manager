"""Use-case tests for GetSkillBoard (fake repos, no Mongo)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
    SkillBoardRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    StudentLevelProgress,
    StudentSkillProgress,
)

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
PROGRAM_ID = "prog-001"
LEVEL_1 = "level-001"
LEVEL_2 = "level-002"


def _level_progress(student_id: str, level_id: str) -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=f"lp-{student_id}",
        academy_id="test-academy",
        student_id=student_id,
        program_id=PROGRAM_ID,
        level_id=level_id,
        status="active",
        started_at=NOW,
        created_at=NOW,
    )


def _skill_progress(
    student_id: str, skill_id: str, level_id: str, status: str
) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{student_id}-{skill_id}",
        academy_id="test-academy",
        student_id=student_id,
        skill_id=skill_id,
        level_id=level_id,
        program_id=PROGRAM_ID,
        status=status,  # type: ignore[arg-type]
        last_updated_at=NOW,
        last_updated_by="coach-001",
    )


class _FakeLevelProgressRepo:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepo:
    def __init__(self, rows: list[StudentSkillProgress]) -> None:
        self._rows = rows

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            row for row in self._rows if row.student_id in student_ids and row.level_id == level_id
        ]


class _FakeRecommendationRepo:
    def __init__(self, by_student: dict[str, object] | None = None) -> None:
        self._by_student = by_student or {}

    async def get_active_for_student(self, student_id: str, program_id: str) -> object | None:
        return self._by_student.get(student_id)


class _FakeSkillLookup:
    """Levels and skills keyed by level_id."""

    def __init__(self) -> None:
        self._levels = {
            LEVEL_1: SimpleNamespace(level_id=LEVEL_1, name="Grip and Control", sequence=1),
            LEVEL_2: SimpleNamespace(level_id=LEVEL_2, name="Net Play", sequence=2),
        }
        self._skills = {
            LEVEL_1: [
                SimpleNamespace(
                    skill_id="skill-a", name="Forehand grip", sequence=1, is_required=True
                ),
                SimpleNamespace(
                    skill_id="skill-b", name="Backhand grip", sequence=2, is_required=True
                ),
                SimpleNamespace(
                    skill_id="skill-c", name="Low serve", sequence=3, is_required=False
                ),
            ],
            LEVEL_2: [
                SimpleNamespace(skill_id="skill-d", name="Net shot", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


def _use_case(
    level_rows: list[StudentLevelProgress],
    skill_rows: list[StudentSkillProgress],
    recs: dict[str, object] | None = None,
) -> GetSkillBoard:
    return GetSkillBoard(
        level_progress=_FakeLevelProgressRepo(level_rows),
        skill_progress=_FakeSkillProgressRepo(skill_rows),
        recommendations=_FakeRecommendationRepo(recs),
        skill_lookup=_FakeSkillLookup(),
    )


def _request(*refs: tuple[str, str]) -> SkillBoardRequest:
    return SkillBoardRequest(
        students=tuple(SkillBoardStudentRef(student_id=s, student_name=n) for s, n in refs),
        program_id=PROGRAM_ID,
        program_name="Skill Pathway",
    )


@pytest.mark.asyncio
async def test_groups_students_by_level_with_statuses() -> None:
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_1), _level_progress("stu-2", LEVEL_1)],
        [
            _skill_progress("stu-1", "skill-a", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "skill-b", LEVEL_1, "PRACTICING"),
            _skill_progress("stu-2", "skill-a", LEVEL_1, "TEST_READY"),
        ],
    )
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-2", "Jaya")))

    assert board.program_id == PROGRAM_ID
    assert len(board.groups) == 1
    group = board.groups[0]
    assert group.level_id == LEVEL_1
    assert group.level_name == "Grip and Control"
    assert [s.skill_id for s in group.skills] == ["skill-a", "skill-b", "skill-c"]

    row1 = next(r for r in group.students if r.student_id == "stu-1")
    assert row1.statuses["skill-a"].status == "PASSED"
    assert row1.statuses["skill-b"].status == "PRACTICING"
    assert row1.statuses["skill-c"].status == "NOT_STARTED"
    assert row1.required_passed == 1
    assert row1.required_total == 2
    assert row1.total_passed == 1
    assert row1.total_count == 3


@pytest.mark.asyncio
async def test_mixed_levels_produce_multiple_groups_sorted_by_sequence() -> None:
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_2), _level_progress("stu-2", LEVEL_1)],
        [],
    )
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-2", "Jaya")))

    assert [g.level_id for g in board.groups] == [LEVEL_1, LEVEL_2]
    assert [g.sequence for g in board.groups] == [1, 2]


@pytest.mark.asyncio
async def test_unplaced_students_listed_separately() -> None:
    use_case = _use_case([_level_progress("stu-1", LEVEL_1)], [])
    board = await use_case.execute(_request(("stu-1", "Netra"), ("stu-3", "Aryan")))

    assert len(board.groups) == 1
    assert [u.student_id for u in board.unplaced] == ["stu-3"]
    assert board.unplaced[0].student_name == "Aryan"


@pytest.mark.asyncio
async def test_level_up_status_included_per_student() -> None:
    rec = SimpleNamespace(status="RECOMMENDED")
    use_case = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [],
        recs={"stu-1": rec},
    )
    board = await use_case.execute(_request(("stu-1", "Netra")))
    assert board.groups[0].students[0].level_up_status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_empty_roster_returns_empty_board() -> None:
    use_case = _use_case([], [])
    board = await use_case.execute(_request())
    assert board.groups == []
    assert board.unplaced == []


@pytest.mark.asyncio
async def test_level_with_no_skills_yields_empty_columns() -> None:
    """A level whose skill lookup returns [] produces a group with skills=[] and zeroed counts."""
    level_empty = "level-empty"
    use_case = _use_case(
        [_level_progress("stu-1", level_empty)],
        [],
    )
    board = await use_case.execute(_request(("stu-1", "Netra")))

    assert len(board.groups) == 1
    group = board.groups[0]
    assert group.level_id == level_empty
    assert group.skills == []

    row = group.students[0]
    assert row.statuses == {}
    assert row.total_count == 0
    assert row.required_total == 0
