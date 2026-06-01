from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.platform.domain.models import Tenant, TenantLimits
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)


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
