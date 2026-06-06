"""Tenant-isolation contract tests for student_progress repositories (ADR-0006).

P1.3 — a functional cross-tenant test. The route-level fakes are not
tenant-aware, so isolation must be proven against the *real* tenant-scoped
Mongo repositories. A query made under one ``academy_id`` must never surface
documents written under another.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.student_progress.domain.models import (
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def _level_progress(student_id: str) -> StudentLevelProgress:
    # academy_id is injected by the repo from the active tenant scope.
    return StudentLevelProgress(
        progress_id=f"lp-{student_id}",
        academy_id="",
        student_id=student_id,
        program_id="prog-1",
        level_id="lvl-1",
        status="active",
        started_at=_NOW,
        completed_at=None,
        created_at=_NOW,
    )


def _skill_progress(student_id: str) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{student_id}",
        academy_id="",
        student_id=student_id,
        skill_id="skill-1",
        level_id="lvl-1",
        program_id="prog-1",
        status="PASSED",
        introduced_at=_NOW,
        last_updated_at=_NOW,
        last_updated_by="coach-1",
    )


def _certificate(student_id: str) -> SkillCertificate:
    return SkillCertificate(
        cert_id=f"cert-{student_id}",
        academy_id="",
        student_id=student_id,
        program_id="prog-1",
        level_id="lvl-1",
        cert_number="CERT-0001",
        student_name="Alice",
        level_name="Level 1",
        program_name="Badminton",
        completed_at=_NOW,
        issued_by="admin-1",
        issued_at=_NOW,
    )


@pytest.mark.asyncio
async def test_level_progress_repo_isolates_tenants(db) -> None:
    repo = MongoStudentLevelProgressRepository(db)
    with tenant_scope("academy-a"):
        await repo.save(_level_progress("stu-a"))

    # academy-A sees its own row.
    with tenant_scope("academy-a"):
        assert await repo.get_active("stu-a", "prog-1") is not None
        assert [p.progress_id for p in await repo.list_for_student("stu-a")] == ["lp-stu-a"]

    # academy-B must see nothing — even for the same student_id.
    with tenant_scope("academy-b"):
        assert await repo.get_active("stu-a", "prog-1") is None
        assert await repo.list_for_student("stu-a") == []


@pytest.mark.asyncio
async def test_skill_progress_repo_isolates_tenants(db) -> None:
    repo = MongoStudentSkillProgressRepository(db)
    with tenant_scope("academy-a"):
        await repo.upsert(_skill_progress("stu-a"))

    with tenant_scope("academy-a"):
        assert await repo.get("stu-a", "skill-1") is not None
        assert len(await repo.list_passed_for_student_level("stu-a", "lvl-1")) == 1

    with tenant_scope("academy-b"):
        assert await repo.get("stu-a", "skill-1") is None
        assert await repo.list_for_student_level("stu-a", "lvl-1") == []
        assert await repo.list_passed_for_student_level("stu-a", "lvl-1") == []


@pytest.mark.asyncio
async def test_certificate_repo_isolates_tenants(db) -> None:
    repo = MongoSkillCertificateRepository(db)
    with tenant_scope("academy-a"):
        await repo.save(_certificate("stu-a"))

    with tenant_scope("academy-a"):
        assert [c.cert_id for c in await repo.list_for_student("stu-a")] == ["cert-stu-a"]

    with tenant_scope("academy-b"):
        assert await repo.list_for_student("stu-a") == []
