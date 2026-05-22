"""Application use cases for SaaS tenant governance and support access."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.governance.domain.errors import GovernancePermissionDenied
from backend.v2.contexts.platform.governance.domain.models import (
    GovernanceActor,
    GovernanceAuditLog,
    PIIHandlingPolicy,
    RetentionPolicy,
    SoftDeletePolicy,
    StudentDataDeletionRequest,
    SupportAccessGrant,
    SupportImpersonationRequest,
    TenantDeletionRequest,
    TenantExportRequest,
)


class TenantGovernanceStore(Protocol):
    """Storage port for governance records and audit rows."""

    async def create_tenant_export_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def create_tenant_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def create_student_data_deletion_request(
        self, request: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def create_support_access_grant(self, grant: dict[str, Any]) -> dict[str, Any]: ...
    async def create_support_impersonation_request(
        self, request: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def append_audit_log(self, audit: dict[str, Any]) -> dict[str, Any]: ...


class GovernanceCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    actor: GovernanceActor
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped


class RequestTenantExportCommand(GovernanceCommand):
    include_pii: bool = False


class RequestTenantDeletionCommand(GovernanceCommand):
    pass


class RequestStudentDataDeletionCommand(GovernanceCommand):
    student_id: str = Field(min_length=1)


class GrantSupportAccessCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    actor: GovernanceActor
    support_user_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    expires_in_hours: int = Field(default=4, ge=1, le=24)

    @field_validator("purpose")
    @classmethod
    def _strip_purpose(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("purpose is required")
        return stripped


class RequestSupportImpersonationCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    actor: GovernanceActor
    target_user_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)

    @field_validator("purpose")
    @classmethod
    def _strip_purpose(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("purpose is required")
        return stripped


class TenantGovernanceService:
    """Coordinates SaaS governance requests and required audit rows."""

    def __init__(
        self,
        *,
        store: TenantGovernanceStore,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._id_factory = id_factory or (lambda prefix: f"{prefix}{uuid4().hex}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def request_tenant_export(
        self, command: RequestTenantExportCommand
    ) -> TenantExportRequest:
        now = self._clock()
        retention = RetentionPolicy().model_dump()
        pii = PIIHandlingPolicy().model_dump()
        request = TenantExportRequest(
            export_request_id=self._id_factory("tenant_export_"),
            academy_id=command.academy_id,
            requested_by_user_id=command.actor.actor_user_id,
            requested_by_membership_id=command.actor.actor_membership_id,
            include_pii=command.include_pii,
            reason=command.reason,
            retention_policy=retention,
            pii_handling_policy=pii,
            created_at=now,
        )
        created = await self._store.create_tenant_export_request(request.model_dump())
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="tenant_export.requested",
            entity_type="tenant_export_request",
            entity_id=request.export_request_id,
            before_snapshot=None,
            after_snapshot=created,
            created_at=now,
        )
        return TenantExportRequest(**created)

    async def request_tenant_deletion(
        self, command: RequestTenantDeletionCommand
    ) -> TenantDeletionRequest:
        now = self._clock()
        soft_delete = SoftDeletePolicy()
        retention = RetentionPolicy()
        request = TenantDeletionRequest(
            deletion_request_id=self._id_factory("tenant_deletion_"),
            academy_id=command.academy_id,
            requested_by_user_id=command.actor.actor_user_id,
            requested_by_membership_id=command.actor.actor_membership_id,
            reason=command.reason,
            hard_delete_allowed=soft_delete.hard_delete_allowed,
            soft_delete_policy=soft_delete.model_dump(),
            retention_policy=retention.model_dump(),
            created_at=now,
        )
        created = await self._store.create_tenant_deletion_request(request.model_dump())
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="tenant_deletion.requested",
            entity_type="tenant_deletion_request",
            entity_id=request.deletion_request_id,
            before_snapshot=None,
            after_snapshot=created,
            created_at=now,
        )
        return TenantDeletionRequest(**created)

    async def request_student_data_deletion(
        self, command: RequestStudentDataDeletionCommand
    ) -> StudentDataDeletionRequest:
        now = self._clock()
        request = StudentDataDeletionRequest(
            student_deletion_request_id=self._id_factory("student_deletion_"),
            academy_id=command.academy_id,
            student_id=command.student_id,
            requested_by_user_id=command.actor.actor_user_id,
            requested_by_membership_id=command.actor.actor_membership_id,
            reason=command.reason,
            soft_delete_policy=SoftDeletePolicy().model_dump(),
            retention_policy=RetentionPolicy().model_dump(),
            pii_handling_policy=PIIHandlingPolicy().model_dump(),
            created_at=now,
        )
        created = await self._store.create_student_data_deletion_request(request.model_dump())
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="student_data_deletion.requested",
            entity_type="student_data_deletion_request",
            entity_id=request.student_deletion_request_id,
            before_snapshot=None,
            after_snapshot=created,
            created_at=now,
        )
        return StudentDataDeletionRequest(**created)

    async def grant_support_access(self, command: GrantSupportAccessCommand) -> SupportAccessGrant:
        self._require_platform_support(command.actor)
        now = self._clock()
        grant = SupportAccessGrant(
            support_access_grant_id=self._id_factory("support_access_"),
            academy_id=command.academy_id,
            support_user_id=command.support_user_id,
            granted_by_user_id=command.actor.actor_user_id,
            granted_by_platform_role=command.actor.platform_role,  # type: ignore[arg-type]
            purpose=command.purpose,
            created_at=now,
            expires_at=now + timedelta(hours=command.expires_in_hours),
        )
        created = await self._store.create_support_access_grant(grant.model_dump())
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="support_access.granted",
            entity_type="support_access_grant",
            entity_id=grant.support_access_grant_id,
            before_snapshot=None,
            after_snapshot=created,
            created_at=now,
        )
        return SupportAccessGrant(**created)

    async def request_support_impersonation(
        self, command: RequestSupportImpersonationCommand
    ) -> SupportImpersonationRequest:
        self._require_platform_support(command.actor)
        now = self._clock()
        request = SupportImpersonationRequest(
            impersonation_request_id=self._id_factory("support_impersonation_"),
            academy_id=command.academy_id,
            target_user_id=command.target_user_id,
            requested_by_user_id=command.actor.actor_user_id,
            requested_by_platform_role=command.actor.platform_role,  # type: ignore[arg-type]
            purpose=command.purpose,
            created_at=now,
        )
        created = await self._store.create_support_impersonation_request(request.model_dump())
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="support_impersonation.requested",
            entity_type="support_impersonation_request",
            entity_id=request.impersonation_request_id,
            before_snapshot=None,
            after_snapshot=created,
            created_at=now,
        )
        return SupportImpersonationRequest(**created)

    async def _append_audit(
        self,
        *,
        actor: GovernanceActor,
        academy_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        before_snapshot: dict[str, Any] | None,
        after_snapshot: dict[str, Any] | None,
        created_at: datetime,
    ) -> None:
        audit = GovernanceAuditLog(
            audit_id=self._id_factory("audit_"),
            actor_user_id=actor.actor_user_id,
            actor_membership_id=actor.actor_membership_id,
            actor_platform_role=actor.platform_role,
            academy_id=academy_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            request_id=actor.request_id,
            ip_address=actor.ip_address,
            created_at=created_at,
        )
        await self._store.append_audit_log(audit.model_dump())

    def _require_platform_support(self, actor: GovernanceActor) -> None:
        if not actor.has_platform_support_access():
            raise GovernancePermissionDenied("platform support role required")
