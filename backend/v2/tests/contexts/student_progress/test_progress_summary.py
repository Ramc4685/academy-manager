"""Tests for shared student progress overview summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    GetProgressSummary,
    ProgressSummaryRequest,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)

pytestmark = pytest.mark.asyncio


NOW = datetime(2026, 6, 5, tzinfo=UTC)


class _LevelProgressRepo:
    def __init__(self, active: StudentLevelProgress | None = None) -> None:
        self._active = active

    async def get_active(self, student_id: str, program_id: str):
        return self._active


class _SkillProgressRepo:
    def __init__(self, progress: list[StudentSkillProgress] | None = None) -> None:
        self._progress = progress or []

    async def list_for_student_level(self, student_id: str, level_id: str):
        return self._progress


class _RecommendationRepo:
    def __init__(self, active: LevelUpRecommendation | None = None) -> None:
        self._active = active

    async def get_active_for_student(self, student_id: str, program_id: str):
        return self._active


class _CertificateRepo:
    def __init__(self, certificates: list[SkillCertificate] | None = None) -> None:
        self._certificates = certificates or []

    async def list_for_student(self, student_id: str):
        return self._certificates


class _SkillLookup:
    def __init__(self, *, level: object | None = None, skills: list[object] | None = None) -> None:
        self._level = level
        self._skills = skills or []

    async def get_level(self, level_id: str):
        return self._level

    async def list_skills_for_level(self, level_id: str):
        return self._skills


def _request() -> ProgressSummaryRequest:
    return ProgressSummaryRequest(
        student_id="student-1",
        student_name="Maya Raman",
        program_id="program-1",
        program_name="Junior Badminton",
    )


def _active_level(level_id: str = "level-1") -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id="progress-1",
        academy_id="academy-1",
        student_id="student-1",
        program_id="program-1",
        level_id=level_id,
        started_at=NOW,
        created_at=NOW,
    )


def _skill(skill_id: str, *, is_required: bool | None = True) -> object:
    fields = {
        "skill_id": skill_id,
        "name": skill_id,
        "sequence": int(skill_id.rsplit("-", maxsplit=1)[-1]),
    }
    if is_required is not None:
        fields["is_required"] = is_required
    return SimpleNamespace(**fields)


def _skill_progress(skill_id: str, status: str) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"progress-{skill_id}",
        academy_id="academy-1",
        student_id="student-1",
        skill_id=skill_id,
        level_id="level-1",
        program_id="program-1",
        status=status,
        last_updated_at=NOW,
        last_updated_by="coach-1",
    )


def _recommendation(status: str = "RECOMMENDED") -> LevelUpRecommendation:
    return LevelUpRecommendation(
        rec_id="rec-1",
        academy_id="academy-1",
        student_id="student-1",
        from_level_id="level-1",
        to_level_id="level-2",
        program_id="program-1",
        status=status,
        recommended_by="coach-1",
        recommended_at=NOW,
    )


def _certificate(level_id: str = "level-1") -> SkillCertificate:
    return SkillCertificate(
        cert_id="cert-1",
        academy_id="academy-1",
        student_id="student-1",
        program_id="program-1",
        level_id=level_id,
        cert_number="CERT-1",
        student_name="Maya Raman",
        level_name="Level 1",
        program_name="Junior Badminton",
        completed_at=NOW,
        issued_by="admin-1",
        issued_at=NOW,
    )


def _use_case(
    *,
    active_level: StudentLevelProgress | None = None,
    skills: list[object] | None = None,
    progress: list[StudentSkillProgress] | None = None,
    recommendation: LevelUpRecommendation | None = None,
    certificates: list[SkillCertificate] | None = None,
) -> GetProgressSummary:
    return GetProgressSummary(
        level_progress=_LevelProgressRepo(active_level),
        skill_progress=_SkillProgressRepo(progress),
        recommendations=_RecommendationRepo(recommendation),
        certificates=_CertificateRepo(certificates),
        skill_lookup=_SkillLookup(
            level=SimpleNamespace(level_id="level-1", name="Level 1", sequence=1),
            skills=skills,
        ),
    )


async def test_student_with_no_active_level_returns_place_in_level():
    result = await _use_case().execute(_request())

    assert result.student_id == "student-1"
    assert result.student_name == "Maya Raman"
    assert result.program_id == "program-1"
    assert result.program_name == "Junior Badminton"
    assert result.current_level_id is None
    assert result.level_completion_status == "not_started"
    assert result.certificate_count == 0
    assert result.next_action == "place_in_level"


async def test_active_level_with_test_ready_required_skill_returns_mastery_counts():
    result = await _use_case(
        active_level=_active_level(),
        skills=[
            _skill("skill-1"),
            _skill("skill-2"),
            _skill("skill-3"),
            _skill("skill-4", is_required=False),
        ],
        progress=[
            _skill_progress("skill-1", "PASSED"),
            _skill_progress("skill-2", "PASSED"),
            _skill_progress("skill-3", "TEST_READY"),
            _skill_progress("skill-4", "PRACTICING"),
        ],
    ).execute(_request())

    assert result.current_level_id == "level-1"
    assert result.current_level_name == "Level 1"
    assert result.current_level_sequence == 1
    assert result.required_skill_count == 3
    assert result.required_skills_passed == 2
    assert result.total_skill_count == 4
    assert result.total_skills_passed == 2
    assert result.in_progress_count == 2
    assert result.not_started_count == 0
    assert result.test_ready_count == 1
    assert result.level_completion_status == "test_ready"
    assert result.next_action == "record_tests"


async def test_all_required_skills_passed_without_recommendation_recommends_level_up():
    result = await _use_case(
        active_level=_active_level(),
        skills=[_skill("skill-1"), _skill("skill-2", is_required=None)],
        progress=[
            _skill_progress("skill-1", "PASSED"),
            _skill_progress("skill-2", "PASSED"),
        ],
    ).execute(_request())

    assert result.required_skill_count == 2
    assert result.required_skills_passed == 2
    assert result.level_completion_status == "complete"
    assert result.next_action == "recommend_level_up"


async def test_active_recommendation_waits_for_admin_approval():
    result = await _use_case(
        active_level=_active_level(),
        skills=[_skill("skill-1")],
        progress=[_skill_progress("skill-1", "PASSED")],
        recommendation=_recommendation(),
    ).execute(_request())

    assert result.level_up_status == "RECOMMENDED"
    assert result.level_completion_status == "complete"
    assert result.next_action == "awaiting_admin_approval"


async def test_certificate_for_current_level_takes_next_action_priority():
    result = await _use_case(
        active_level=_active_level(),
        skills=[_skill("skill-1")],
        progress=[_skill_progress("skill-1", "PASSED")],
        recommendation=_recommendation(),
        certificates=[_certificate()],
    ).execute(_request())

    assert result.certificate_count == 1
    assert result.level_up_status == "RECOMMENDED"
    assert result.next_action == "certificate_issued"
