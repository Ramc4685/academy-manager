"""Application tests for platform-owned tenant lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    CreateTenantCommand,
    TenantLifecycleService,
    UpdateTenantPlanCommand,
)
from backend.v2.contexts.platform.domain.errors import (
    TenantAlreadyExists,
    TenantInvalidTransition,
    TenantNotFound,
)
from backend.v2.contexts.platform.domain.models import Tenant, TenantLimits


class FakeTenantRepository:
    def __init__(self) -> None:
        self.tenants: dict[str, Tenant] = {}
        self.slug_index: dict[str, str] = {}
        self.domain_index: dict[str, str] = {}

    async def get_by_id(self, academy_id: str) -> Tenant | None:
        return self.tenants.get(academy_id)

    async def list_tenants(self) -> list[Tenant]:
        return list(self.tenants.values())

    async def get_by_slug(self, slug: str) -> Tenant | None:
        academy_id = self.slug_index.get(slug)
        return self.tenants.get(academy_id) if academy_id else None

    async def get_by_domain(self, domain: str) -> Tenant | None:
        academy_id = self.domain_index.get(domain)
        return self.tenants.get(academy_id) if academy_id else None

    async def create(self, tenant: Tenant) -> Tenant:
        self.tenants[tenant.academy_id] = tenant
        self.slug_index[tenant.slug] = tenant.academy_id
        self.domain_index[tenant.primary_domain] = tenant.academy_id
        return tenant

    async def save(self, tenant: Tenant) -> Tenant:
        self.tenants[tenant.academy_id] = tenant
        self.slug_index[tenant.slug] = tenant.academy_id
        self.domain_index[tenant.primary_domain] = tenant.academy_id
        return tenant


def _clock() -> datetime:
    return datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


def _service(repo: FakeTenantRepository) -> TenantLifecycleService:
    return TenantLifecycleService(
        tenants=repo,
        id_factory=lambda prefix: f"{prefix}001",
        clock=_clock,
    )


def _create_command(**overrides: object) -> CreateTenantCommand:
    values: dict[str, object] = {
        "display_name": "North Shore Badminton",
        "slug": "North_Shore",
        "primary_domain": "North.Example.COM.",
        "plan_code": "starter",
        "limits": {"max_students": 100, "max_coaches": 8},
        "actor_user_id": "platform-admin",
    }
    values.update(overrides)
    return CreateTenantCommand(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_tenant_starts_in_provisioning_and_normalizes_contract_fields() -> None:
    repo = FakeTenantRepository()

    tenant = await _service(repo).create_tenant(_create_command())

    assert tenant.academy_id == "tenant_001"
    assert tenant.slug == "north-shore"
    assert tenant.primary_domain == "north.example.com"
    assert tenant.status == "provisioning"
    assert tenant.plan_code == "starter"
    assert tenant.limits == TenantLimits(max_students=100, max_coaches=8)
    assert tenant.is_servable() is False
    assert tenant.created_by == "platform-admin"


@pytest.mark.asyncio
async def test_lifecycle_state_machine_allows_expected_transitions() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())

    active = await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    suspended = await service.suspend_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
        reason="payment_failed",
    )
    reactivated = await service.reactivate_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
    )
    cancelled = await service.cancel_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
        reason="customer_request",
    )
    restored = await service.reactivate_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
    )

    assert [
        active.status,
        suspended.status,
        reactivated.status,
        cancelled.status,
        restored.status,
    ] == [
        "active",
        "suspended",
        "active",
        "cancelled",
        "active",
    ]
    assert suspended.status_reason == "payment_failed"
    assert cancelled.cancelled_at == _clock()
    assert restored.reactivated_at == _clock()


@pytest.mark.asyncio
async def test_invalid_lifecycle_transition_is_rejected() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())

    with pytest.raises(TenantInvalidTransition, match="provisioning -> suspended"):
        await service.suspend_tenant(tenant.academy_id, actor_user_id="platform-admin")


@pytest.mark.asyncio
async def test_cancelled_tenant_plan_limits_cannot_be_mutated_until_reactivated() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())
    await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    await service.cancel_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
        reason="customer_request",
    )

    with pytest.raises(TenantInvalidTransition, match="cancelled tenant"):
        await service.update_plan_limits(
            tenant.academy_id,
            UpdateTenantPlanCommand(
                plan_code="growth",
                limits={"max_students": 300, "max_coaches": 24},
                actor_user_id="platform-admin",
            ),
        )

    await service.reactivate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    updated = await service.update_plan_limits(
        tenant.academy_id,
        UpdateTenantPlanCommand(
            plan_code="growth",
            limits={"max_students": 300, "max_coaches": 24},
            actor_user_id="platform-admin",
        ),
    )

    assert updated.plan_code == "growth"
    assert updated.limits.max_students == 300
    assert updated.limits.max_coaches == 24


@pytest.mark.asyncio
async def test_tenant_health_reports_serving_status_before_requests_are_allowed() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())

    provisioning = await service.get_tenant_health(tenant.academy_id)
    active = await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    active_health = await service.get_tenant_health(active.academy_id)
    await service.suspend_tenant(
        tenant.academy_id,
        actor_user_id="platform-admin",
        reason="policy_review",
    )
    suspended = await service.get_tenant_health(tenant.academy_id)

    assert provisioning.servable is False
    assert provisioning.reason == "tenant_status_provisioning"
    assert active_health.servable is True
    assert active_health.reason is None
    assert suspended.servable is False
    assert suspended.reason == "tenant_status_suspended"


@pytest.mark.asyncio
async def test_create_rejects_duplicate_slug_or_domain() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    await service.create_tenant(_create_command())

    with pytest.raises(TenantAlreadyExists, match="slug"):
        await service.create_tenant(_create_command(primary_domain="other.example.com"))

    with pytest.raises(TenantAlreadyExists, match="domain"):
        await service.create_tenant(_create_command(slug="other"))


@pytest.mark.asyncio
async def test_missing_tenant_is_reported_as_not_found() -> None:
    with pytest.raises(TenantNotFound, match="missing"):
        await _service(FakeTenantRepository()).get_tenant("missing")
