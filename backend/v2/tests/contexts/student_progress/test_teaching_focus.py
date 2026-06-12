"""Use-case tests for GetTeachingFocus (fake repos, no Mongo)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    GetTeachingFocus,
    TeachingFocusRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    StudentLevelProgress,
    StudentSkillProgress,
)

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
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
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        self.calls.append((tuple(student_ids), level_id))
        return [
            row for row in self._rows if row.student_id in student_ids and row.level_id == level_id
        ]


class _FakeSkillLookup:
    """Level 1 has 3 required + 1 optional; level 2 has 1 required skill."""

    def __init__(self) -> None:
        self._levels = {
            LEVEL_1: SimpleNamespace(level_id=LEVEL_1, name="Grip and Control", sequence=1),
            LEVEL_2: SimpleNamespace(level_id=LEVEL_2, name="Net Play", sequence=2),
        }
        self._skills = {
            LEVEL_1: [
                SimpleNamespace(
                    skill_id="sk-a", name="Forehand grip", sequence=1, is_required=True
                ),
                SimpleNamespace(
                    skill_id="sk-b", name="Backhand grip", sequence=2, is_required=True
                ),
                SimpleNamespace(skill_id="sk-c", name="Ready stance", sequence=3, is_required=True),
                SimpleNamespace(
                    skill_id="sk-opt", name="Trick serve", sequence=4, is_required=False
                ),
            ],
            LEVEL_2: [
                SimpleNamespace(skill_id="sk-d", name="Net shot", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


def _use_case(
    level_rows: list[StudentLevelProgress],
    skill_rows: list[StudentSkillProgress],
) -> tuple[GetTeachingFocus, _FakeSkillProgressRepo]:
    skill_repo = _FakeSkillProgressRepo(skill_rows)
    return (
        GetTeachingFocus(
            level_progress=_FakeLevelProgressRepo(level_rows),
            skill_progress=skill_repo,
            skill_lookup=_FakeSkillLookup(),
        ),
        skill_repo,
    )


def _request(*refs: tuple[str, str]) -> TeachingFocusRequest:
    return TeachingFocusRequest(
        students=tuple(SkillBoardStudentRef(student_id=s, student_name=n) for s, n in refs),
        program_id=PROGRAM_ID,
    )


def _focus_for(result, student_id: str):
    for group in result.groups:
        for student in group.students:
            if student.student_id == student_id:
                return student
    raise AssertionError(f"{student_id} not found in groups")


@pytest.mark.asyncio
async def test_missing_progress_row_means_not_started_first_required() -> None:
    """No skill progress at all → focus the first required skill, NOT_STARTED."""
    use_case, _ = _use_case([_level_progress("stu-1", LEVEL_1)], [])
    result = await use_case.execute(_request(("stu-1", "Alice")))

    focus = _focus_for(result, "stu-1")
    assert focus.focus == "practice"
    assert focus.next_skill is not None
    assert focus.next_skill.skill_id == "sk-a"
    assert focus.next_skill.status == "NOT_STARTED"
    assert focus.next_skill.is_review is False


@pytest.mark.asyncio
async def test_first_non_passed_required_by_sequence() -> None:
    """First required is PASSED → focus the next required by sequence."""
    use_case, _ = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [
            _skill_progress("stu-1", "sk-a", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-b", LEVEL_1, "PRACTICING"),
        ],
    )
    result = await use_case.execute(_request(("stu-1", "Alice")))
    focus = _focus_for(result, "stu-1")
    assert focus.focus == "practice"
    assert focus.next_skill.skill_id == "sk-b"
    assert focus.next_skill.status == "PRACTICING"


@pytest.mark.asyncio
async def test_needs_review_takes_precedence_over_unpassed_required() -> None:
    """A later required skill in NEEDS_REVIEW beats an earlier unpassed one."""
    use_case, _ = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [
            # sk-a not passed (would be practice pick) but sk-b needs review
            _skill_progress("stu-1", "sk-b", LEVEL_1, "NEEDS_REVIEW"),
        ],
    )
    result = await use_case.execute(_request(("stu-1", "Alice")))
    focus = _focus_for(result, "stu-1")
    assert focus.focus == "review"
    assert focus.next_skill.skill_id == "sk-b"
    assert focus.next_skill.is_review is True


@pytest.mark.asyncio
async def test_lowest_sequence_needs_review_required_wins() -> None:
    use_case, _ = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [
            _skill_progress("stu-1", "sk-a", LEVEL_1, "NEEDS_REVIEW"),
            _skill_progress("stu-1", "sk-b", LEVEL_1, "NEEDS_REVIEW"),
        ],
    )
    result = await use_case.execute(_request(("stu-1", "Alice")))
    focus = _focus_for(result, "stu-1")
    assert focus.next_skill.skill_id == "sk-a"


@pytest.mark.asyncio
async def test_all_required_passed_falls_back_to_optional() -> None:
    use_case, _ = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [
            _skill_progress("stu-1", "sk-a", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-b", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-c", LEVEL_1, "PASSED"),
        ],
    )
    result = await use_case.execute(_request(("stu-1", "Alice")))
    focus = _focus_for(result, "stu-1")
    assert focus.focus == "practice"
    assert focus.next_skill.skill_id == "sk-opt"


@pytest.mark.asyncio
async def test_all_skills_passed_is_ready_for_level_up() -> None:
    use_case, _ = _use_case(
        [_level_progress("stu-1", LEVEL_1)],
        [
            _skill_progress("stu-1", "sk-a", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-b", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-c", LEVEL_1, "PASSED"),
            _skill_progress("stu-1", "sk-opt", LEVEL_1, "PASSED"),
        ],
    )
    result = await use_case.execute(_request(("stu-1", "Alice")))
    focus = _focus_for(result, "stu-1")
    assert focus.focus == "ready_for_level_up"
    assert focus.next_skill is None


@pytest.mark.asyncio
async def test_unplaced_students_listed_separately() -> None:
    use_case, _ = _use_case([_level_progress("stu-1", LEVEL_1)], [])
    result = await use_case.execute(_request(("stu-1", "Alice"), ("stu-x", "Zed")))
    assert [u.student_id for u in result.unplaced] == ["stu-x"]
    assert result.unplaced[0].student_name == "Zed"


@pytest.mark.asyncio
async def test_groups_sorted_by_level_sequence_and_students_by_name() -> None:
    use_case, _ = _use_case(
        [
            _level_progress("stu-1", LEVEL_2),
            _level_progress("stu-2", LEVEL_1),
            _level_progress("stu-3", LEVEL_1),
        ],
        [],
    )
    result = await use_case.execute(_request(("stu-1", "Bob"), ("stu-2", "Zoe"), ("stu-3", "Amy")))
    assert [g.level_id for g in result.groups] == [LEVEL_1, LEVEL_2]
    assert [g.level_sequence for g in result.groups] == [1, 2]
    # Level 1 students sorted by name
    assert [s.student_name for s in result.groups[0].students] == ["Amy", "Zoe"]


@pytest.mark.asyncio
async def test_per_level_batching_one_query_per_level() -> None:
    use_case, skill_repo = _use_case(
        [_level_progress("stu-1", LEVEL_1), _level_progress("stu-2", LEVEL_1)],
        [],
    )
    await use_case.execute(_request(("stu-1", "Alice"), ("stu-2", "Bob")))
    # One batched call for the single level, both student ids passed together.
    assert len(skill_repo.calls) == 1
    student_ids, level_id = skill_repo.calls[0]
    assert set(student_ids) == {"stu-1", "stu-2"}
    assert level_id == LEVEL_1
