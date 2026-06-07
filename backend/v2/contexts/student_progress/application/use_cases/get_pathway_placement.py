"""Use case: resolve canonical pathway placement for a student/program."""

from __future__ import annotations

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    ProgressNextAction,
    StudentPathwayPlacement,
)


class StudentPathwayPlacementRequest(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    program_id: str


class GetStudentPathwayPlacement:
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

    async def execute(self, request: StudentPathwayPlacementRequest) -> StudentPathwayPlacement:
        active = await self._level_progress.get_active(request.student_id, request.program_id)
        if active is None:
            return StudentPathwayPlacement(
                student_id=request.student_id,
                program_id=request.program_id,
            )

        level = await self._skill_lookup.get_level(active.level_id)
        skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        progress = await self._skill_progress.list_for_student_level(
            request.student_id,
            active.level_id,
        )
        progress_by_skill = {row.skill_id: row for row in progress}

        completed = 0
        ready_for_test = 0
        for skill in skills:
            skill_id = skill.skill_id  # type: ignore[attr-defined]
            status = getattr(progress_by_skill.get(skill_id), "status", "NOT_STARTED")
            if status == "PASSED":
                completed += 1
            elif status == "TEST_READY":
                ready_for_test += 1

        total = len(skills)
        completion_percentage = round((completed / total) * 100) if total else 0

        return StudentPathwayPlacement(
            student_id=request.student_id,
            program_id=request.program_id,
            progress_id=active.progress_id,
            level_id=active.level_id,
            level_sequence=getattr(level, "sequence", None) if level else None,
            level_name=getattr(level, "name", None) if level else None,
            placement_status=active.status,
            next_action=_next_action(
                total=total, completed=completed, ready_for_test=ready_for_test
            ),
            skills_total=total,
            skills_completed=completed,
            skills_ready_for_test=ready_for_test,
            completion_percentage=completion_percentage,
        )


def _next_action(*, total: int, completed: int, ready_for_test: int) -> ProgressNextAction:
    if total > 0 and completed == total:
        return "recommend_level_up"
    if ready_for_test > 0:
        return "record_tests"
    return "continue_practice"
