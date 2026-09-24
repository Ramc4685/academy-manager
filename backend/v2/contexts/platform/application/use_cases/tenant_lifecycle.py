"""Tenant lifecycle use cases owned by the Platform context."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.application.ports import TenantLifecycleRepository
from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.domain.errors import (
    TenantAgreementNotAccepted,
    TenantAlreadyExists,
    TenantInvalidTransition,
    TenantNotFound,
)
from backend.v2.contexts.platform.domain.models import Tenant, TenantHealth, TenantLimits
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: Async callable that persists a single platform_audit_events row.
#: Provided by the composition root; injected into TenantLifecycleService
#: so each state transition leaves an auditable trail (fixes #80).
AuditRecorder = Callable[[RecordPlatformAuditEventCommand], Awaitable[None]]


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


class RecordAgreementAcceptanceCommand(BaseModel):
    """A platform admin records that the academy accepted the platform agreement.

    ``accepted_by`` names the academy-side signatory (for example the owner's
    email); ``actor_user_id`` is the platform admin who recorded it and lands
    in ``updated_by`` and the audit trail. The agreement text itself is an
    owner/legal input (docs/platform/platform-agreement.md), versioned by
    ``agreement_version``.
    """

    agreement_version: str = Field(min_length=1, max_length=64)
    accepted_by: str = Field(min_length=1, max_length=200)
    actor_user_id: str = Field(min_length=1)

    @field_validator("agreement_version", "accepted_by", "actor_user_id")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field is required")
        return stripped


class TenantLifecycleService:
    """Application service for platform tenant lifecycle operations."""

    def __init__(
        self,
        *,
        tenants: TenantLifecycleRepository,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self._tenants = tenants
        self._id_factory = id_factory or (lambda prefix: f"{prefix}{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._audit_recorder = audit_recorder

    async def _emit_audit(
        self,
        *,
        actor_user_id: str,
        academy_id: str,
        action: str,
        entity_id: str,
        before: Tenant | None,
        after: Tenant,
    ) -> None:
        """Append one platform_audit_events row for a lifecycle transition.

        Failures are logged but do not propagate — an audit gap must
        never break the underlying state transition the caller is
        depending on. The audit-emission outage is its own observability
        signal.
        """
        if self._audit_recorder is None:
            return
        try:
            await self._audit_recorder(
                RecordPlatformAuditEventCommand(
                    actor_user_id=actor_user_id,
                    academy_id=academy_id,
                    action=action,
                    entity_type="tenant",
                    entity_id=entity_id,
                    before_snapshot=before.model_dump(mode="json") if before else None,
                    after_snapshot=after.model_dump(mode="json"),
                )
            )
        except Exception as exc:
            log.warning(
                "tenant_lifecycle_audit_emit_failed action=%s tenant=%s err=%s",
                action,
                entity_id,
                exc,
            )

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
        created = await self._tenants.create(tenant)
        await self._emit_audit(
            actor_user_id=command.actor_user_id,
            academy_id=created.academy_id,
            action="tenant.created",
            entity_id=created.academy_id,
            before=None,
            after=created,
        )
        return created

    async def get_tenant(self, academy_id: str) -> Tenant:
        tenant = await self._tenants.get_by_id(academy_id)
        if tenant is None:
            raise TenantNotFound(f"tenant not found: {academy_id}")
        return tenant

    async def list_tenants(self) -> list[Tenant]:
        """Return every tenant the platform knows about, newest first.

        Read-only operator view backing the platform tenants list; no audit
        event is emitted because nothing changes.
        """
        tenants = await self._tenants.list_tenants()
        return sorted(tenants, key=lambda tenant: tenant.created_at, reverse=True)

    async def get_tenant_health(self, academy_id: str) -> TenantHealth:
        return (await self.get_tenant(academy_id)).health()

    async def activate_tenant(self, academy_id: str, *, actor_user_id: str) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(tenant, {"provisioning"}, target_status="active")
        if not tenant.has_accepted_platform_agreement():
            raise TenantAgreementNotAccepted(
                "tenant cannot be activated until the platform agreement acceptance is recorded",
                academy_id=academy_id,
            )
        now = self._clock()
        saved = await self._tenants.save(
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
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.activated",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

    async def record_agreement_acceptance(
        self,
        academy_id: str,
        command: RecordAgreementAcceptanceCommand,
    ) -> Tenant:
        """Store who accepted which platform agreement version, and when.

        Recording a newer version replaces the fields on the tenant; the
        previous acceptance stays in the platform audit trail (before
        snapshot). A cancelled tenant cannot take a new acceptance.
        """
        tenant = await self.get_tenant(academy_id)
        if tenant.status == "cancelled":
            raise TenantInvalidTransition(
                "cannot record an agreement acceptance for a cancelled tenant",
                academy_id=academy_id,
                status=tenant.status,
            )
        now = self._clock()
        saved = await self._tenants.save(
            tenant.model_copy(
                update={
                    "platform_agreement_version": command.agreement_version,
                    "platform_agreement_accepted_at": now,
                    "platform_agreement_accepted_by": command.accepted_by,
                    "updated_at": now,
                    "updated_by": command.actor_user_id,
                }
            )
        )
        await self._emit_audit(
            actor_user_id=command.actor_user_id,
            academy_id=academy_id,
            action="tenant.agreement_accepted",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

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
        saved = await self._tenants.save(
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
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.suspended",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

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
        saved = await self._tenants.save(
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
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.cancelled",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

    async def reactivate_tenant(self, academy_id: str, *, actor_user_id: str) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        self._require_status(tenant, {"suspended", "cancelled"}, target_status="active")
        now = self._clock()
        saved = await self._tenants.save(
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
        await self._emit_audit(
            actor_user_id=actor_user_id,
            academy_id=academy_id,
            action="tenant.reactivated",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

    async def update_plan_limits(
        self,
        academy_id: str,
        command: UpdateTenantPlanCommand,
    ) -> Tenant:
        tenant = await self.get_tenant(academy_id)
        if tenant.status == "cancelled":
            raise TenantInvalidTransition("cannot update plan limits for a cancelled tenant")
        now = self._clock()
        saved = await self._tenants.save(
            tenant.model_copy(
                update={
                    "plan_code": command.plan_code,
                    "limits": command.limits,
                    "updated_at": now,
                    "updated_by": command.actor_user_id,
                }
            )
        )
        await self._emit_audit(
            actor_user_id=command.actor_user_id,
            academy_id=academy_id,
            action="tenant.plan_updated",
            entity_id=academy_id,
            before=tenant,
            after=saved,
        )
        return saved

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
