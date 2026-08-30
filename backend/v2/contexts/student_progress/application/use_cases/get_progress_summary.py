"""Use case: get a shared student progress overview for a program."""

from __future__ import annotations

from collections.abc import Sequence

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
    LevelUpRecommendation,
    ProgressNextAction,
    SkillCertificate,
    StudentLevelProgress,
    StudentProgressOverview,
    StudentSkillProgress,
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

        if active is None:
            return self._unplaced_overview(request, rec=rec, certs=certs)

        level = await self._skill_lookup.get_level(active.level_id)
        skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        progress = await self._skill_progress.list_for_student_level(
            request.student_id,
            active.level_id,
        )
        return self._placed_overview(
            request,
            active=active,
            rec=rec,
            certs=certs,
            level=level,
            skills=skills,
            progress=progress,
        )

    async def execute_many(
        self, requests: Sequence[ProgressSummaryRequest]
    ) -> list[StudentProgressOverview]:
        """Batch variant of :meth:`execute` for roster-sized inputs.

        Issues a constant number of queries per distinct active level instead
        of ~6 sequential queries per student (the N+1 pattern the coach
        pre-class views used to hit).
        """
        if not requests:
            return []

        student_ids = [request.student_id for request in requests]
        program_id = requests[0].program_id

        active_rows = await self._level_progress.list_active_for_students(student_ids, program_id)
        active_by_student = {row.student_id: row for row in active_rows}

        certs_by_student: dict[str, list[SkillCertificate]] = {}
        for cert in await self._certs.list_for_students(student_ids):
            certs_by_student.setdefault(cert.student_id, []).append(cert)

        rec_by_student = {
            rec.student_id: rec
            for rec in await self._recommendations.list_active_for_students(student_ids, program_id)
        }

        students_by_level: dict[str, list[str]] = {}
        for student_id in student_ids:
            active = active_by_student.get(student_id)
            if active is not None:
                students_by_level.setdefault(active.level_id, []).append(student_id)

        level_by_id: dict[str, object | None] = {}
        skills_by_level: dict[str, list[object]] = {}
        progress_by_student: dict[str, list[StudentSkillProgress]] = {}
        for level_id, level_student_ids in students_by_level.items():
            level_by_id[level_id] = await self._skill_lookup.get_level(level_id)
            skills_by_level[level_id] = await self._skill_lookup.list_skills_for_level(level_id)
            for row in await self._skill_progress.list_for_students(level_student_ids, level_id):
                progress_by_student.setdefault(row.student_id, []).append(row)

        overviews: list[StudentProgressOverview] = []
        for request in requests:
            active = active_by_student.get(request.student_id)
            rec = rec_by_student.get(request.student_id)
            certs = certs_by_student.get(request.student_id, [])
            if active is None:
                overviews.append(self._unplaced_overview(request, rec=rec, certs=certs))
                continue
            overviews.append(
                self._placed_overview(
                    request,
                    active=active,
                    rec=rec,
                    certs=certs,
                    level=level_by_id.get(active.level_id),
                    skills=skills_by_level.get(active.level_id, []),
                    progress=progress_by_student.get(request.student_id, []),
                )
            )
        return overviews

    @staticmethod
    def _unplaced_overview(
        request: ProgressSummaryRequest,
        *,
        rec: LevelUpRecommendation | None,
        certs: Sequence[SkillCertificate],
    ) -> StudentProgressOverview:
        return StudentProgressOverview(
            student_id=request.student_id,
            student_name=request.student_name,
            program_id=request.program_id,
            program_name=request.program_name,
            level_up_status=getattr(rec, "status", None) if rec else None,
            certificate_count=len(certs),
            next_action="place_in_level",
        )

    def _placed_overview(
        self,
        request: ProgressSummaryRequest,
        *,
        active: StudentLevelProgress,
        rec: LevelUpRecommendation | None,
        certs: Sequence[SkillCertificate],
        level: object | None,
        skills: Sequence[object],
        progress: Sequence[StudentSkillProgress],
    ) -> StudentProgressOverview:
        level_up_status = getattr(rec, "status", None) if rec else None
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
