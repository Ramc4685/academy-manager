"""Certificate detail over a REAL mongod: tenant and student scoping.

The real certificate repo is tenant-scoped, and the use case scopes by
student, so a certificate id from another academy or another child never
resolves. Skipped when no mongod is reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.application.use_cases.get_certificate_detail import (
    GetCertificateDetail,
    GetCertificateDetailCommand,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-cert"
OTHER = "acad-other"
AT = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)


def _cert(academy: str, cert_id: str, student_id: str) -> dict[str, Any]:
    return {
        "academy_id": academy,
        "cert_id": cert_id,
        "student_id": student_id,
        "program_id": "prog",
        "level_id": "L1",
        "cert_number": f"N-{cert_id}",
        "student_name": "Aarav Test",
        "level_name": "Grip and Control",
        "program_name": "Badminton Pathway",
        "completed_at": AT,
        "issued_by": "system:auto_level_up",
        "issued_at": AT,
    }


async def _seed(db: Any) -> None:
    common = {
        "academy_id": ACADEMY,
        "program_id": "prog",
        "is_active": True,
        "created_at": AT,
        "updated_at": AT,
        "created_by": "owner",
    }
    await db["skill_levels"].insert_many(
        [
            {**common, "level_id": "L1", "sequence": 1, "name": "Grip and Control"},
            {**common, "level_id": "L2", "sequence": 2, "name": "Net and Movement"},
        ]
    )
    await db["skills"].insert_many(
        [
            {**common, "skill_id": "s1", "level_id": "L1", "sequence": 1, "name": "Thumb grip"},
            {**common, "skill_id": "s2", "level_id": "L1", "sequence": 2, "name": "V grip"},
        ]
    )
    await db["skill_certificates"].insert_many(
        [
            _cert(ACADEMY, "mine", "kid-1"),
            _cert(ACADEMY, "sibling-elsewhere", "kid-2"),
            # Same student id in another tenant: must never leak across.
            _cert(OTHER, "other-tenant", "kid-1"),
        ]
    )


def _use_case(db: Any) -> GetCertificateDetail:
    return GetCertificateDetail(
        certificates=MongoSkillCertificateRepository(db),
        skill_lookup=CurriculumSkillLookupAdapter(
            skill_repo=MongoSkillRepository(db), level_repo=MongoLevelRepository(db)
        ),
    )


async def test_own_certificate_resolves_with_curriculum_fields(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        detail = await _use_case(real_db).execute(
            GetCertificateDetailCommand(student_id="kid-1", cert_id="mine")
        )

    assert detail is not None
    assert detail.certificate.cert_number == "N-mine"
    assert detail.level_number == 1
    assert detail.skills == ["Thumb grip", "V grip"]
    assert detail.next_level is not None and detail.next_level.name == "Net and Movement"


async def test_other_childs_and_other_tenants_certificates_do_not_resolve(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        other_child = await _use_case(real_db).execute(
            GetCertificateDetailCommand(student_id="kid-1", cert_id="sibling-elsewhere")
        )
        other_tenant = await _use_case(real_db).execute(
            GetCertificateDetailCommand(student_id="kid-1", cert_id="other-tenant")
        )

    assert other_child is None
    assert other_tenant is None
