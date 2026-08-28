from __future__ import annotations

import logging
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


@pytest.mark.asyncio
async def test_list_tenants_skips_invalid_legacy_docs_and_warns_with_academy_id(
    db, caplog: pytest.LogCaptureFixture
) -> None:
    """A legacy `academies` row must not take the whole operator list down.

    It is skipped, but the skip has to be observable: the warning names the
    offending academy id so an operator can find the row that was dropped.
    """
    repo = MongoTenantLifecycleRepository(db)
    await repo.create(_tenant())
    # Legacy row: predates the platform context, so it has no domain at all
    # and cannot satisfy `Tenant`.
    await db["academies"].insert_one(
        {"academy_id": "acad_legacy_no_domain", "name": "Legacy Academy"}
    )

    with caplog.at_level(
        logging.WARNING,
        logger="backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo",
    ):
        tenants = await repo.list_tenants()

    assert [t.academy_id for t in tenants] == ["tenant_north"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "acad_legacy_no_domain" in warnings[0].getMessage()
