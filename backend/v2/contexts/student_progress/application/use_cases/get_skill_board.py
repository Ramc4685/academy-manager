"""Use case: build the session skill board (students x skills, grouped by level)."""

from __future__ import annotations

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    SkillBoardCell,
    SkillBoardLevelGroup,
    SkillBoardResult,
    SkillBoardSkill,
    SkillBoardStudentRef,
    SkillBoardStudentRow,
)


class SkillBoardRequest(BaseModel):
    model_config = {"frozen": True}

    students: tuple[SkillBoardStudentRef, ...]
    program_id: str
    program_name: str


class GetSkillBoard:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recommendations = recommendations
        self._skill_lookup = skill_lookup

    async def execute(self, request: SkillBoardRequest) -> SkillBoardResult:
        by_level: dict[str, list[SkillBoardStudentRef]] = {}
        unplaced: list[SkillBoardStudentRef] = []

        for ref in request.students:
            active = await self._level_progress.get_active(ref.student_id, request.program_id)
            if active is None:
                unplaced.append(ref)
            else:
                by_level.setdefault(active.level_id, []).append(ref)

        groups: list[SkillBoardLevelGroup] = []
        for level_id, refs in by_level.items():
            level = await self._skill_lookup.get_level(level_id)
            skills = await self._skill_lookup.list_skills_for_level(level_id)
            skill_cols = sorted(
                (
                    SkillBoardSkill(
                        skill_id=str(skill.skill_id),  # type: ignore[attr-defined]
                        name=str(getattr(skill, "name", "")),
                        sequence=int(getattr(skill, "sequence", 0)),
                        is_required=bool(getattr(skill, "is_required", True)),
                    )
                    for skill in skills
                ),
                key=lambda s: s.sequence,
            )

            progress_rows = await self._skill_progress.list_for_students(
                [ref.student_id for ref in refs], level_id
            )
            cells_by_student: dict[str, dict[str, SkillBoardCell]] = {}
            for row in progress_rows:
                cells_by_student.setdefault(row.student_id, {})[row.skill_id] = SkillBoardCell(
                    status=row.status,
                    last_updated_at=row.last_updated_at,
                )

            student_rows: list[SkillBoardStudentRow] = []
            for ref in refs:
                cells = cells_by_student.get(ref.student_id, {})
                statuses = {
                    col.skill_id: cells.get(col.skill_id, SkillBoardCell()) for col in skill_cols
                }
                required = [col for col in skill_cols if col.is_required]
                rec = await self._recommendations.get_active_for_student(
                    ref.student_id, request.program_id
                )
                student_rows.append(
                    SkillBoardStudentRow(
                        student_id=ref.student_id,
                        student_name=ref.student_name,
                        statuses=statuses,
                        required_passed=sum(
                            1 for col in required if statuses[col.skill_id].status == "PASSED"
                        ),
                        required_total=len(required),
                        total_passed=sum(
                            1 for col in skill_cols if statuses[col.skill_id].status == "PASSED"
                        ),
                        total_count=len(skill_cols),
                        level_up_status=getattr(rec, "status", None) if rec else None,
                    )
                )
            student_rows.sort(key=lambda r: r.student_name.lower())

            groups.append(
                SkillBoardLevelGroup(
                    level_id=level_id,
                    level_name=str(getattr(level, "name", level_id)),
                    sequence=int(getattr(level, "sequence", 0)),
                    skills=skill_cols,
                    students=student_rows,
                )
            )

        groups.sort(key=lambda g: g.sequence)
        return SkillBoardResult(
            program_id=request.program_id,
            program_name=request.program_name,
            groups=groups,
            unplaced=unplaced,
        )
