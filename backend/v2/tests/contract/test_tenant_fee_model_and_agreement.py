"""L9c on a real mongod: migration 0200 backfill, repository round trip and
the activation guard, with every migration (and the ``academies`` validator)
applied.

The backfill must set ``fee_model`` to ``flat_monthly`` and leave the
agreement fields null: an existing academy has not accepted any agreement, so
none is fabricated. A recorded acceptance survives a re-run.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    CreateTenantCommand,
    RecordAgreementAcceptanceCommand,
    TenantLifecycleService,
)
from backend.v2.contexts.platform.domain.errors import TenantAgreementNotAccepted
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)

_M0200 = importlib.import_module("backend.v2.migrations.0200_tenant_fee_model_and_agreement")

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _legacy_academy(academy_id: str) -> dict[str, object]:
    """An academy doc as written before L9c (no fee model, no agreement)."""
    return {
        "academy_id": academy_id,
        "display_name": "Synthetic Shuttle Club",
        "slug": academy_id,
        "primary_domain": f"{academy_id}.example.test",
        "status": "active",
        "plan_code": "starter",
        "created_at": _NOW,
        "updated_at": _NOW,
    }


@pytest.mark.asyncio
async def test_backfill_sets_flat_monthly_and_null_agreement_fields(real_db) -> None:
    await real_db["academies"].insert_one(_legacy_academy("acad_legacy"))

    await _M0200.up(real_db)

    doc = await real_db["academies"].find_one({"academy_id": "acad_legacy"})
    assert doc is not None
    assert doc["fee_model"] == "flat_monthly"
    for field in _M0200.AGREEMENT_FIELDS:
        assert field in doc
        assert doc[field] is None
    # Status is untouched: an active academy keeps serving.
    assert doc["status"] == "active"

    tenant = await MongoTenantLifecycleRepository(real_db).get_by_id("acad_legacy")
    assert tenant is not None
    assert tenant.fee_model == "flat_monthly"
    assert tenant.has_accepted_platform_agreement() is False


@pytest.mark.asyncio
async def test_backfill_rerun_never_overwrites_a_recorded_acceptance(real_db) -> None:
    accepted = _legacy_academy("acad_accepted") | {
        "fee_model": "flat_monthly",
        "platform_agreement_version": "2026-10-draft",
        "platform_agreement_accepted_at": _NOW,
        "platform_agreement_accepted_by": "owner@example.test",
    }
    await real_db["academies"].insert_one(accepted)

    await _M0200.up(real_db)
    await _M0200.up(real_db)

    doc = await real_db["academies"].find_one({"academy_id": "acad_accepted"})
    assert doc is not None
    assert doc["platform_agreement_version"] == "2026-10-draft"
    assert doc["platform_agreement_accepted_by"] == "owner@example.test"
    assert doc["platform_agreement_accepted_at"].replace(tzinfo=UTC) == _NOW


@pytest.mark.asyncio
async def test_activation_requires_a_persisted_acceptance(real_db) -> None:
    service = TenantLifecycleService(
        tenants=MongoTenantLifecycleRepository(real_db),
        id_factory=lambda prefix: f"{prefix}l9c",
        clock=lambda: _NOW,
    )
    tenant = await service.create_tenant(
        CreateTenantCommand(
            display_name="Synthetic Racquet Academy",
            slug="synthetic-racquet",
            primary_domain="synthetic-racquet.example.test",
            plan_code="starter",
            actor_user_id="platform-admin",
        )
    )
    stored = await real_db["academies"].find_one({"academy_id": tenant.academy_id})
    assert stored is not None
    assert stored["fee_model"] == "flat_monthly"
    assert stored["platform_agreement_accepted_at"] is None

    with pytest.raises(TenantAgreementNotAccepted):
        await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    unchanged = await real_db["academies"].find_one({"academy_id": tenant.academy_id})
    assert unchanged is not None
    assert unchanged["status"] == "provisioning"

    await service.record_agreement_acceptance(
        tenant.academy_id,
        RecordAgreementAcceptanceCommand(
            agreement_version="2026-10-draft",
            accepted_by="owner@example.test",
            actor_user_id="platform-admin",
        ),
    )
    active = await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    assert active.status == "active"

    reread = await MongoTenantLifecycleRepository(real_db).get_by_id(tenant.academy_id)
    assert reread is not None
    assert reread.status == "active"
    assert reread.platform_agreement_version == "2026-10-draft"
    assert reread.platform_agreement_accepted_by == "owner@example.test"
    assert reread.platform_agreement_accepted_at is not None
