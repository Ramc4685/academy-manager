"""Application tests for platform-owned tenant lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    CreateTenantCommand,
    RecordAgreementAcceptanceCommand,
    TenantLifecycleService,
    UpdateTenantPlanCommand,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.domain.errors import (
    TenantAgreementNotAccepted,
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


async def _accept(service: TenantLifecycleService, academy_id: str) -> Tenant:
    return await service.record_agreement_acceptance(
        academy_id,
        RecordAgreementAcceptanceCommand(
            agreement_version="2026-10-draft",
            accepted_by="owner@example.test",
            actor_user_id="platform-admin",
        ),
    )


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
    assert tenant.fee_model == "flat_monthly"
    assert tenant.platform_agreement_version is None
    assert tenant.platform_agreement_accepted_at is None
    assert tenant.platform_agreement_accepted_by is None


@pytest.mark.asyncio
async def test_lifecycle_state_machine_allows_expected_transitions() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())

    await _accept(service, tenant.academy_id)
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
    await _accept(service, tenant.academy_id)
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
    await _accept(service, tenant.academy_id)
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


@pytest.mark.asyncio
async def test_activation_is_refused_without_an_agreement_acceptance() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())

    with pytest.raises(TenantAgreementNotAccepted, match="platform agreement"):
        await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")

    assert (await service.get_tenant(tenant.academy_id)).status == "provisioning"


@pytest.mark.asyncio
async def test_recording_acceptance_stores_version_time_and_signatory() -> None:
    repo = FakeTenantRepository()
    audits: list[RecordPlatformAuditEventCommand] = []

    async def _record(command: RecordPlatformAuditEventCommand) -> None:
        audits.append(command)

    service = TenantLifecycleService(
        tenants=repo,
        id_factory=lambda prefix: f"{prefix}001",
        clock=_clock,
        audit_recorder=_record,
    )
    tenant = await service.create_tenant(_create_command())

    accepted = await service.record_agreement_acceptance(
        tenant.academy_id,
        RecordAgreementAcceptanceCommand(
            agreement_version="  2026-10-draft ",
            accepted_by=" owner@example.test ",
            actor_user_id="platform-admin",
        ),
    )

    assert accepted.platform_agreement_version == "2026-10-draft"
    assert accepted.platform_agreement_accepted_by == "owner@example.test"
    assert accepted.platform_agreement_accepted_at == _clock()
    assert accepted.updated_by == "platform-admin"
    assert accepted.has_accepted_platform_agreement() is True
    assert accepted.status == "provisioning"
    assert audits[-1].action == "tenant.agreement_accepted"
    assert audits[-1].before_snapshot is not None
    assert audits[-1].before_snapshot["platform_agreement_version"] is None

    active = await service.activate_tenant(tenant.academy_id, actor_user_id="platform-admin")
    assert active.status == "active"
    assert active.platform_agreement_version == "2026-10-draft"


@pytest.mark.asyncio
async def test_cancelled_tenant_cannot_take_a_new_acceptance() -> None:
    repo = FakeTenantRepository()
    service = _service(repo)
    tenant = await service.create_tenant(_create_command())
    await service.cancel_tenant(
        tenant.academy_id, actor_user_id="platform-admin", reason="customer_request"
    )

    with pytest.raises(TenantInvalidTransition, match="cancelled tenant"):
        await _accept(service, tenant.academy_id)


def test_acceptance_command_rejects_blank_version_or_signatory() -> None:
    with pytest.raises(ValueError):
        RecordAgreementAcceptanceCommand(
            agreement_version="   ", accepted_by="owner@example.test", actor_user_id="a"
        )
    with pytest.raises(ValueError):
        RecordAgreementAcceptanceCommand(
            agreement_version="v1", accepted_by="  ", actor_user_id="a"
        )


def test_tenant_counts_as_accepted_only_with_all_three_fields() -> None:
    base = {
        "academy_id": "tenant_x",
        "display_name": "Synthetic Club",
        "slug": "synthetic",
        "primary_domain": "synthetic.example.test",
        "plan_code": "starter",
        "created_by": "platform-admin",
        "updated_by": "platform-admin",
        "created_at": _clock(),
        "updated_at": _clock(),
    }
    assert Tenant(**base).has_accepted_platform_agreement() is False  # type: ignore[arg-type]
    partial = Tenant(**base, platform_agreement_version="v1")  # type: ignore[arg-type]
    assert partial.has_accepted_platform_agreement() is False
    full = Tenant(
        **base,  # type: ignore[arg-type]
        platform_agreement_version="v1",
        platform_agreement_accepted_at=_clock(),
        platform_agreement_accepted_by="owner@example.test",
    )
    assert full.has_accepted_platform_agreement() is True
