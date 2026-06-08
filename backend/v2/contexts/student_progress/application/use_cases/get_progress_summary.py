"""Use case: get a shared student progress overview for a program."""

from __future__ import annotations

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelCompletionStatus,
    ProgressNextAction,
    StudentProgressOverview,
)


class ProgressSummaryRequest(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    program_id: str
    program_name: str


class GetProgressSummary:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        certificates: CertificateRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recommendations = recommendations
        self._certs = certificates
        self._skill_lookup = skill_lookup

    async def execute(self, request: ProgressSummaryRequest) -> StudentProgressOverview:
        active = await self._level_progress.get_active(request.student_id, request.program_id)
        certs = await self._certs.list_for_student(request.student_id)
        rec = await self._recommendations.get_active_for_student(
            request.student_id,
            request.program_id,
        )
        level_up_status = getattr(rec, "status", None) if rec else None

        if active is None:
            return StudentProgressOverview(
                student_id=request.student_id,
                student_name=request.student_name,
                program_id=request.program_id,
                program_name=request.program_name,
                level_up_status=level_up_status,
                certificate_count=len(certs),
                next_action="place_in_level",
            )

        level = await self._skill_lookup.get_level(active.level_id)
        skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        progress = await self._skill_progress.list_for_student_level(
            request.student_id,
            active.level_id,
        )
        progress_by_skill = {row.skill_id: row for row in progress}

        required_skill_count = 0
        required_skills_passed = 0
        total_skills_passed = 0
        in_progress_count = 0
        not_started_count = 0
        test_ready_count = 0

        for skill in skills:
            skill_id = skill.skill_id  # type: ignore[attr-defined]
            is_required = getattr(skill, "is_required", True)
            status = getattr(progress_by_skill.get(skill_id), "status", "NOT_STARTED")

            if is_required:
                required_skill_count += 1

            if status == "PASSED":
                total_skills_passed += 1
                if is_required:
                    required_skills_passed += 1
            elif status == "NOT_STARTED":
                not_started_count += 1
            else:
                in_progress_count += 1
                if status == "TEST_READY":
                    test_ready_count += 1

        total_skill_count = len(skills)
        required_complete = (
            required_skill_count > 0 and required_skills_passed == required_skill_count
        )
        level_completion_status = self._level_completion_status(
            required_complete=required_complete,
            test_ready_count=test_ready_count,
            total_skill_count=total_skill_count,
            progress_count=len(progress),
        )
        next_action = self._next_action(
            has_current_level_certificate=any(
                getattr(cert, "level_id", None) == active.level_id for cert in certs
            ),
            has_recommendation=rec is not None,
            required_complete=required_complete,
            test_ready_count=test_ready_count,
        )

        return StudentProgressOverview(
            student_id=request.student_id,
            student_name=request.student_name,
            program_id=request.program_id,
            program_name=request.program_name,
            current_level_id=active.level_id,
            current_level_name=getattr(level, "name", None) if level else None,
            current_level_sequence=getattr(level, "sequence", None) if level else None,
            required_skill_count=required_skill_count,
            required_skills_passed=required_skills_passed,
            total_skill_count=total_skill_count,
            total_skills_passed=total_skills_passed,
            in_progress_count=in_progress_count,
            not_started_count=not_started_count,
            test_ready_count=test_ready_count,
            level_completion_status=level_completion_status,
            level_up_status=level_up_status,
            certificate_count=len(certs),
            next_action=next_action,
        )

    @staticmethod
    def _level_completion_status(
        *,
        required_complete: bool,
        test_ready_count: int,
        total_skill_count: int,
        progress_count: int,
    ) -> LevelCompletionStatus:
        if required_complete:
            return "complete"
        if test_ready_count > 0:
            return "test_ready"
        if total_skill_count > 0 or progress_count > 0:
            return "in_progress"
        return "not_started"

    @staticmethod
    def _next_action(
        *,
        has_current_level_certificate: bool,
        has_recommendation: bool,
        required_complete: bool,
        test_ready_count: int,
    ) -> ProgressNextAction:
        if has_current_level_certificate:
            return "certificate_issued"
        if has_recommendation:
            return "awaiting_admin_approval"
        if required_complete:
            return "recommend_level_up"
        if test_ready_count > 0:
            return "record_tests"
        return "continue_practice"
