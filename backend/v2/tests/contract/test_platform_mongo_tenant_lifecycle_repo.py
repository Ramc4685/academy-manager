from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.platform.domain.models import Tenant, TenantLimits
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)
from backend.v2.main import _AcademyLookupAdapter


def _tenant(**overrides: object) -> Tenant:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    values = {
        "academy_id": "tenant_north",
        "display_name": "North Academy",
        "slug": "north",
        "primary_domain": "north-academy.courtmastr.com",
        "status": "provisioning",
        "plan_code": "starter",
        "limits": TenantLimits(),
        "created_by": "platform-admin",
        "updated_by": "platform-admin",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Tenant(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_tenant_writes_verified_academy_domain_mapping(db) -> None:
    repo = MongoTenantLifecycleRepository(db)

    await repo.create(_tenant())

    domain = await db["academy_domains"].find_one({"domain": "north-academy.courtmastr.com"})
    assert domain is not None
    assert domain["academy_id"] == "tenant_north"
    assert domain["slug"] == "north"
    assert domain["status"] == "verified"
    assert domain["kind"] == "tenant_subdomain"


@pytest.mark.asyncio
async def test_academy_lookup_resolves_verified_domain_mapping(db) -> None:
    await db["academies"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "slug": "blno-badminton",
            "primary_domain": "blno-badminton.academy.courtmastr.com",
            "custom_domain": "blno-badminton.academy.courtmastr.com",
        }
    )
    await db["academy_domains"].insert_one(
        {
            "domain": "blno-academy.courtmastr.com",
            "academy_id": "acad_blno_badminton",
            "slug": "blno",
            "status": "verified",
            "kind": "tenant_subdomain",
        }
    )

    lookup = _AcademyLookupAdapter(MongoAcademyRepository(db))

    assert await lookup.find_by_domain("blno-academy.courtmastr.com") == "acad_blno_badminton"
