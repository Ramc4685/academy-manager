"""Use case: select the next skill to teach each student (grouped by level).

Pure next-skill selection that mirrors :class:`GetSkillBoard` — same repo
ports, same per-level batching (no N+1). Selection priority per student
within their active level:

1. **Review** — lowest-sequence *required* skill marked ``NEEDS_REVIEW``.
2. **Practice** — first non-``PASSED`` *required* skill by sequence.
3. **Optional fallback** — a ``NEEDS_REVIEW`` optional skill, else the first
   non-``PASSED`` optional skill by sequence.
4. **Ready for level-up** — every skill is ``PASSED`` (no next skill).

A student with no progress row for a skill is treated as ``NOT_STARTED``.
Students with no active level are returned as ``unplaced``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardStudentRef,
    StudentTeachingFocus,
    TeachingFocusLevelGroup,
    TeachingFocusResult,
    TeachingFocusSkill,
)


class TeachingFocusRequest(BaseModel):
    model_config = {"frozen": True}

    students: tuple[SkillBoardStudentRef, ...]
    program_id: str


def _pick_next_skill(skills_sorted: list[Any], status_of: Any) -> Any | None:
    """Return the skill to focus on next, or ``None`` if all are passed.

    ``skills_sorted`` is ordered by sequence; ``status_of(skill)`` yields the
    student's current :class:`SkillStatus` for that skill.
    """
    required = [s for s in skills_sorted if bool(getattr(s, "is_required", True))]
    optional = [s for s in skills_sorted if not bool(getattr(s, "is_required", True))]

    for skill in required:
        if status_of(skill) == "NEEDS_REVIEW":
            return skill
    for skill in required:
        if status_of(skill) != "PASSED":
            return skill
    for skill in optional:
        if status_of(skill) == "NEEDS_REVIEW":
            return skill
    for skill in optional:
        if status_of(skill) != "PASSED":
            return skill
    return None


class GetTeachingFocus:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup

    async def for_students(
        self, students: list[tuple[str, str]], program_id: str
    ) -> TeachingFocusResult:
        """Convenience entry point taking ``(student_id, student_name)`` tuples.

        Lets cross-context orchestrators (e.g. the coach teaching plan) call this
        use case without importing student_progress request/domain types.
        """
        return await self.execute(
            TeachingFocusRequest(
                students=tuple(
                    SkillBoardStudentRef(student_id=sid, student_name=name)
                    for sid, name in students
                ),
                program_id=program_id,
            )
        )

    async def execute(self, request: TeachingFocusRequest) -> TeachingFocusResult:
        by_level: dict[str, list[SkillBoardStudentRef]] = {}
        unplaced: list[SkillBoardStudentRef] = []

        for ref in request.students:
            active = await self._level_progress.get_active(ref.student_id, request.program_id)
            if active is None:
                unplaced.append(ref)
            else:
                by_level.setdefault(active.level_id, []).append(ref)

        groups: list[TeachingFocusLevelGroup] = []
        for level_id, refs in by_level.items():
            level = await self._skill_lookup.get_level(level_id)
            skills = await self._skill_lookup.list_skills_for_level(level_id)
            skills_sorted = sorted(skills, key=lambda s: int(getattr(s, "sequence", 0)))

            progress_rows = await self._skill_progress.list_for_students(
                [ref.student_id for ref in refs], level_id
            )
            status_by_student: dict[str, dict[str, str]] = {}
            for row in progress_rows:
                status_by_student.setdefault(row.student_id, {})[row.skill_id] = row.status

            students: list[StudentTeachingFocus] = []
            for ref in refs:
                statuses = status_by_student.get(ref.student_id, {})

                def status_of(skill: Any, _statuses: dict[str, str] = statuses) -> str:
                    return _statuses.get(str(getattr(skill, "skill_id", "")), "NOT_STARTED")

                selected = _pick_next_skill(skills_sorted, status_of)
                if selected is None:
                    students.append(
                        StudentTeachingFocus(
                            student_id=ref.student_id,
                            student_name=ref.student_name,
                            focus="ready_for_level_up",
                            next_skill=None,
                        )
                    )
                    continue

                status = status_of(selected)
                is_review = status == "NEEDS_REVIEW"
                students.append(
                    StudentTeachingFocus(
                        student_id=ref.student_id,
                        student_name=ref.student_name,
                        focus="review" if is_review else "practice",
                        next_skill=TeachingFocusSkill(
                            skill_id=str(getattr(selected, "skill_id", "")),
                            name=str(getattr(selected, "name", "")),
                            sequence=int(getattr(selected, "sequence", 0)),
                            level_id=level_id,
                            status=status,
                            is_review=is_review,
                        ),
                    )
                )
            students.sort(key=lambda s: s.student_name.lower())

            groups.append(
                TeachingFocusLevelGroup(
                    level_id=level_id,
                    level_name=str(getattr(level, "name", level_id)),
                    level_sequence=int(getattr(level, "sequence", 0)),
                    students=students,
                )
            )

        groups.sort(key=lambda g: g.level_sequence)
        return TeachingFocusResult(
            program_id=request.program_id,
            groups=groups,
            unplaced=unplaced,
        )
