"""Tenant lifecycle use cases owned by the Platform context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.application.ports import TenantLifecycleRepository
from backend.v2.contexts.platform.domain.errors import (
    TenantAlreadyExists,
    TenantInvalidTransition,
    TenantNotFound,
)
from backend.v2.contexts.platform.domain.models import Tenant, TenantHealth, TenantLimits
from backend.v2.shared.ids import new_ulid


class CreateTenantCommand(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    plan_code: str = Field(min_length=1)
    limits: TenantLimits = Field(default_factory=TenantLimits)
    actor_user_id: str = Field(min_length=1)

    @field_validator("display_name", "plan_code", "actor_user_id")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        normalized = "-".join(part for part in normalized.split("-") if part)
        if not normalized:
            raise ValueError("slug is required")
        return normalized

    @field_validator("primary_domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not normalized:
            raise ValueError("primary_domain is required")
        return normalized


class UpdateTenantPlanCommand(BaseModel):
    plan_code: str = Field(min_length=1)
    limits: TenantLimits = Field(default_factory=TenantLimits)
    actor_user_id: str = Field(min_length=1)

    @field_validator("plan_code", "actor_user_id")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()


class TenantLifecycleService:
    """Application service for platform tenant lifecycle operations."""

    def __init__(
        self,
        *,
        tenants: TenantLifecycleRepository,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tenants = tenants
        self._id_factory = id_factory or (lambda prefix: f"{prefix}{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_tenant(self, command: CreateTenantCommand) -> Tenant:
        if await self._tenants.get_by_slug(command.slug):
            raise TenantAlreadyExists(f"tenant slug already exists: {command.slug}")
        if await self._tenants.get_by_domain(command.primary_domain):
            raise TenantAlreadyExists(f"tenant domain already exists: {command.primary_domain}")

        now = self._clock()
        tenant = Tenant(
            academy_id=self._id_factory("tenant_"),
            display_name=command.display_name,
            slug=command.slug,
            primary_domain=command.primary_domain,
            status="provisioning",
            plan_code=command.plan_code,
            limits=command.limits,
            created_by=command.actor_user_id,
            updated_by=command.actor_user_id,
            created_at=now,
            updated_at=now,
        )
        return await self._tenants.create(tenant)

    async def get_tenant(self, academy_id: str) -> Tenant:
        tenant = await self._tenants.get_by_id(academy_id)
        if tenant is None:
            raise TenantNotFound(f"tenant not found: {academy_id}")
        return tenant

    async def get_tenant_health(self, academy_id: str) -> TenantHealth:
        return (await self.get_tenant(academy_id)).health()

    async def activate_tenant(self, academy_id: str, *, actor_user_id: str) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(tenant, {"provisioning"}, target_status="active")
        now = self._clock()
        return await self._tenants.save(
            tenant.model_copy(
                update={
                    "status": "active",
                    "status_reason": None,
                    "activated_at": now,
                    "updated_at": now,
                    "updated_by": actor_user_id,
                }
            )
        )

    async def suspend_tenant(
        self,
        academy_id: str,
        *,
        actor_user_id: str,
        reason: str = "",
    ) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(tenant, {"active"}, target_status="suspended")
        now = self._clock()
        return await self._tenants.save(
            tenant.model_copy(
                update={
                    "status": "suspended",
                    "status_reason": reason.strip() or None,
                    "suspended_at": now,
                    "updated_at": now,
                    "updated_by": actor_user_id,
                }
            )
        )

    async def cancel_tenant(
        self,
        academy_id: str,
        *,
        actor_user_id: str,
        reason: str,
    ) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(
            tenant,
            {"provisioning", "active", "suspended"},
            target_status="cancelled",
        )
        now = self._clock()
        return await self._tenants.save(
            tenant.model_copy(
                update={
                    "status": "cancelled",
                    "status_reason": reason.strip() or None,
                    "cancelled_at": now,
                    "updated_at": now,
                    "updated_by": actor_user_id,
                }
            )
        )

    async def reactivate_tenant(self, academy_id: str, *, actor_user_id: str) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(tenant, {"suspended", "cancelled"}, target_status="active")
        now = self._clock()
        return await self._tenants.save(
            tenant.model_copy(
                update={
                    "status": "active",
                    "status_reason": None,
                    "reactivated_at": now,
                    "updated_at": now,
                    "updated_by": actor_user_id,
                }
            )
        )

    async def update_plan_limits(
        self,
        academy_id: str,
        command: UpdateTenantPlanCommand,
    ) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        if tenant.status == "cancelled":
            raise TenantInvalidTransition("cannot update plan limits for a cancelled tenant")
        now = self._clock()
        return await self._tenants.save(
            tenant.model_copy(
                update={
                    "plan_code": command.plan_code,
                    "limits": command.limits,
                    "updated_at": now,
                    "updated_by": command.actor_user_id,
                }
            )
        )

    @staticmethod
    def _require_status(tenant: Tenant, allowed: set[str], *, target_status: str) -> None:
        if tenant.status not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise TenantInvalidTransition(
                f"invalid tenant status transition: {tenant.status} -> {target_status}; "
                f"expected current status in: {allowed_text}",
                academy_id=tenant.academy_id,
                status=tenant.status,
            )
