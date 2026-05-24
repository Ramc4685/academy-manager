"""Application use cases for SaaS tenant governance and support access."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.governance.domain.errors import (
    GovernancePermissionDenied,
    GovernanceRequestNotFound,
)
from backend.v2.contexts.platform.governance.domain.models import (
    GovernanceActor,
    GovernanceAuditLog,
    GovernanceRequestStatus,
    PIIHandlingPolicy,
    RetentionPolicy,
    SoftDeletePolicy,
    StudentDataDeletionRequest,
    SupportAccessGrant,
    SupportImpersonationRequest,
    TenantDeletionRequest,
    TenantExportRequest,
)

log = logging.getLogger(__name__)

AuditRecorder = Callable[[RecordPlatformAuditEventCommand], Awaitable[object]]


class TenantGovernanceStore(Protocol):
    """Storage port for governance records and audit rows."""

    async def create_tenant_export_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def get_tenant_export_request(self, request_id: str) -> dict[str, Any] | None: ...
    async def list_tenant_export_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def update_tenant_export_request(
        self, request_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def create_tenant_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def list_tenant_deletion_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def create_student_data_deletion_request(
        self, request: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def list_student_data_deletion_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def create_support_access_grant(self, grant: dict[str, Any]) -> dict[str, Any]: ...
    async def list_support_access_grants(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def revoke_support_access_grant(
        self, grant_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    async def create_support_impersonation_request(
        self, request: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def list_support_impersonation_requests(
        self, academy_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def get_request_status(self, request_id: str) -> dict[str, Any] | None: ...
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


class RevokeSupportAccessCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    actor: GovernanceActor
    support_access_grant_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped


class TenantGovernanceService:
    """Coordinates SaaS governance requests and required audit rows."""

    def __init__(
        self,
        *,
        store: TenantGovernanceStore,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self._store = store
        self._id_factory = id_factory or (lambda prefix: f"{prefix}{uuid4().hex}")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._audit_recorder = audit_recorder

    def configure_audit_recorder(self, audit_recorder: AuditRecorder) -> None:
        self._audit_recorder = audit_recorder

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

    async def list_tenant_export_requests(
        self, *, academy_id: str | None = None
    ) -> list[TenantExportRequest]:
        return [
            TenantExportRequest(**item)
            for item in await self._store.list_tenant_export_requests(academy_id)
        ]

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

    async def list_tenant_deletion_requests(
        self, *, academy_id: str | None = None
    ) -> list[TenantDeletionRequest]:
        return [
            TenantDeletionRequest(**item)
            for item in await self._store.list_tenant_deletion_requests(academy_id)
        ]

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

    async def list_student_data_deletion_requests(
        self, *, academy_id: str | None = None
    ) -> list[StudentDataDeletionRequest]:
        return [
            StudentDataDeletionRequest(**item)
            for item in await self._store.list_student_data_deletion_requests(academy_id)
        ]

    async def grant_support_access(self, command: GrantSupportAccessCommand) -> SupportAccessGrant:
        self._require_platform_support(command.actor)
        now = self._clock()
        grant = SupportAccessGrant(
            support_access_grant_id=self._id_factory("support_access_"),
            academy_id=command.academy_id,
            support_user_id=command.support_user_id,
            granted_by_user_id=command.actor.actor_user_id,
            granted_by_platform_role=command.actor.platform_role,
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

    async def list_support_access_grants(
        self, *, academy_id: str | None = None
    ) -> list[SupportAccessGrant]:
        return [
            SupportAccessGrant(**item)
            for item in await self._store.list_support_access_grants(academy_id)
        ]

    async def revoke_support_access(
        self, command: RevokeSupportAccessCommand
    ) -> SupportAccessGrant:
        self._require_platform_support(command.actor)
        now = self._clock()
        revoked = await self._store.revoke_support_access_grant(
            command.support_access_grant_id,
            {
                "status": "revoked",
                "revoked_at": now,
                "revoked_by_user_id": command.actor.actor_user_id,
                "revoke_reason": command.reason,
            },
        )
        if revoked is None:
            raise GovernanceRequestNotFound(
                f"support access grant not found: {command.support_access_grant_id}"
            )
        await self._append_audit(
            actor=command.actor,
            academy_id=command.academy_id,
            action="support_access.revoked",
            entity_type="support_access_grant",
            entity_id=command.support_access_grant_id,
            before_snapshot=None,
            after_snapshot=revoked,
            created_at=now,
        )
        return SupportAccessGrant(**revoked)

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
            requested_by_platform_role=command.actor.platform_role,
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

    async def list_support_impersonation_requests(
        self, *, academy_id: str | None = None
    ) -> list[SupportImpersonationRequest]:
        return [
            SupportImpersonationRequest(**item)
            for item in await self._store.list_support_impersonation_requests(academy_id)
        ]

    async def get_request_status(self, request_id: str) -> GovernanceRequestStatus:
        status = await self._store.get_request_status(request_id)
        if status is None:
            raise GovernanceRequestNotFound(f"governance request not found: {request_id}")
        return GovernanceRequestStatus(**status)

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
        await self._append_platform_audit(audit)

    def _require_platform_support(self, actor: GovernanceActor) -> None:
        if not actor.has_platform_support_access():
            raise GovernancePermissionDenied("platform support role required")

    async def _append_platform_audit(self, audit: GovernanceAuditLog) -> None:
        if self._audit_recorder is None:
            return
        try:
            await self._audit_recorder(
                RecordPlatformAuditEventCommand(
                    actor_user_id=audit.actor_user_id,
                    actor_membership_id=audit.actor_membership_id,
                    academy_id=audit.academy_id,
                    platform_actor_role=audit.actor_platform_role,
                    action=audit.action,
                    entity_type=audit.entity_type,
                    entity_id=audit.entity_id,
                    before_snapshot=audit.before_snapshot,
                    after_snapshot=audit.after_snapshot,
                    request_id=audit.request_id,
                    ip_address=audit.ip_address,
                )
            )
        except Exception as exc:
            log.warning(
                "platform_governance_audit_emit_failed action=%s entity=%s err=%s",
                audit.action,
                audit.entity_id,
                exc,
            )
