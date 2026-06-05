"""Use case: get the skill passport for a student's active level in a program."""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
    TestAttemptRepository,
)
from backend.v2.contexts.student_progress.domain.errors import StudentNotPlaced
from backend.v2.contexts.student_progress.domain.models import SkillPassportEntry


@dataclass(frozen=True)
class GetStudentPassportCommand:
    student_id: str
    program_id: str


class GetStudentPassport:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        test_attempts: TestAttemptRepository,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._test_attempts = test_attempts

    async def execute(self, cmd: GetStudentPassportCommand) -> list[SkillPassportEntry]:
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level",
                student_id=cmd.student_id,
                program_id=cmd.program_id,
            )

        all_skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        skill_progs = await self._skill_progress.list_for_student_level(
            cmd.student_id, active.level_id
        )
        prog_by_skill = {sp.skill_id: sp for sp in skill_progs}

        entries: list[SkillPassportEntry] = []
        for skill in all_skills:
            skill_id = skill.skill_id  # type: ignore[attr-defined]
            prog = prog_by_skill.get(skill_id)
            status = prog.status if prog else "NOT_STARTED"

            attempts = await self._test_attempts.list_for_student_skill(cmd.student_id, skill_id)
            attempt_count = len(attempts)
            last_passed: bool | None = None
            last_tested_at = None
            if attempts:
                last_attempt = max(attempts, key=lambda a: a.tested_at)
                last_passed = last_attempt.passed
                last_tested_at = last_attempt.tested_at

            entries.append(
                SkillPassportEntry(
                    skill_id=skill_id,
                    skill_name=getattr(skill, "name", ""),
                    skill_description=getattr(skill, "description", ""),
                    sequence=getattr(skill, "sequence", 0),
                    is_required=getattr(skill, "is_required", True),
                    status=status,
                    last_test_passed=last_passed,
                    last_tested_at=last_tested_at,
                    test_attempt_count=attempt_count,
                )
            )

        return sorted(entries, key=lambda e: e.sequence)
