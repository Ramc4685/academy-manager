"""Use case: get aggregated student progress for a program."""

from __future__ import annotations

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    SkillPassportEntry,
    StudentProgressSummary,
)


class GetStudentProgress:
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

    async def execute(self, student_id: str, program_id: str) -> StudentProgressSummary:
        active = await self._level_progress.get_active(student_id, program_id)
        certs = await self._certs.list_for_student(student_id)
        level_up_rec = await self._recommendations.get_active_for_student(student_id, program_id)

        if active is None:
            return StudentProgressSummary(
                student_id=student_id,
                program_id=program_id,
                program_name="",
                current_level_id=None,
                current_level_name=None,
                current_level_sequence=None,
                total_skills=0,
                passed_skills=0,
                in_progress_skills=0,
                not_started_skills=0,
                level_up_status=None,
                certificates=certs,
            )

        level_meta = await self._skill_lookup.get_level(active.level_id)
        level_name = getattr(level_meta, "name", "") if level_meta else ""
        level_sequence = getattr(level_meta, "sequence", None) if level_meta else None

        skill_progs = await self._skill_progress.list_for_student_level(student_id, active.level_id)
        total = len(skill_progs)
        passed = sum(1 for sp in skill_progs if sp.status == "PASSED")
        not_started = sum(1 for sp in skill_progs if sp.status == "NOT_STARTED")
        in_progress = total - passed - not_started

        return StudentProgressSummary(
            student_id=student_id,
            program_id=program_id,
            program_name="",
            current_level_id=active.level_id,
            current_level_name=level_name,
            current_level_sequence=level_sequence,
            total_skills=total,
            passed_skills=passed,
            in_progress_skills=in_progress,
            not_started_skills=not_started,
            level_up_status=level_up_rec.status if level_up_rec else None,
            certificates=certs,
        )


class GetStudentPassport:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        test_attempts: object,  # TestAttemptRepository
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._test_attempts = test_attempts

    async def execute(self, student_id: str, program_id: str) -> list[SkillPassportEntry]:
        active = await self._level_progress.get_active(student_id, program_id)
        if active is None:
            return []

        all_skills = await self._skill_lookup.list_skills_for_level(active.level_id)
        skill_progs = await self._skill_progress.list_for_student_level(student_id, active.level_id)
        prog_by_skill = {sp.skill_id: sp for sp in skill_progs}

        entries: list[SkillPassportEntry] = []
        for skill in all_skills:
            skill_id = skill.skill_id  # type: ignore[attr-defined]
            prog = prog_by_skill.get(skill_id)
            status = prog.status if prog else "NOT_STARTED"

            # Get test attempt summary
            attempt_count = 0
            last_passed: bool | None = None
            last_tested_at = None
            attempts_repo = self._test_attempts
            if hasattr(attempts_repo, "list_for_student_skill"):
                attempts = await attempts_repo.list_for_student_skill(student_id, skill_id)
                attempt_count = len(attempts)
                if attempts:
                    last_attempt = max(attempts, key=lambda a: a.tested_at)
                    last_passed = last_attempt.passed
                    last_tested_at = last_attempt.tested_at

            entries.append(
                SkillPassportEntry(
                    skill_id=skill_id,
                    level_id=active.level_id,
                    program_id=program_id,
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


class GetLevelUpQueue:
    def __init__(
        self,
        *,
        recommendations: LevelUpRecommendationRepository,
    ) -> None:
        self._recs = recommendations

    async def execute(self) -> list[LevelUpRecommendation]:
        return await self._recs.list_pending()


class GetStudentCertificates:
    def __init__(self, *, certificates: CertificateRepository) -> None:
        self._certs = certificates

    async def execute(self, student_id: str) -> list[SkillCertificate]:
        return await self._certs.list_for_student(student_id)
