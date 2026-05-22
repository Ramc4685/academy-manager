"""Application tests for SaaS tenant governance and support access."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.platform.governance.application.use_cases import (
    GrantSupportAccessCommand,
    RequestStudentDataDeletionCommand,
    RequestSupportImpersonationCommand,
    RequestTenantDeletionCommand,
    RequestTenantExportCommand,
    TenantGovernanceService,
)
from backend.v2.contexts.platform.governance.domain.models import (
    GovernanceActor,
    PIIHandlingPolicy,
    RetentionPolicy,
    SoftDeletePolicy,
)
from backend.v2.contexts.platform.governance.domain.errors import GovernancePermissionDenied


class FakeGovernanceStore:
    def __init__(self) -> None:
        self.tenant_exports: dict[str, dict[str, Any]] = {}
        self.tenant_deletions: dict[str, dict[str, Any]] = {}
        self.student_deletions: dict[str, dict[str, Any]] = {}
        self.support_access_grants: dict[str, dict[str, Any]] = {}
        self.support_impersonation_requests: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []

    async def create_tenant_export_request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.tenant_exports[request["export_request_id"]] = dict(request)
        return dict(request)

    async def create_tenant_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.tenant_deletions[request["deletion_request_id"]] = dict(request)
        return dict(request)

    async def create_student_data_deletion_request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.student_deletions[request["student_deletion_request_id"]] = dict(request)
        return dict(request)

    async def create_support_access_grant(self, grant: dict[str, Any]) -> dict[str, Any]:
        self.support_access_grants[grant["support_access_grant_id"]] = dict(grant)
        return dict(grant)

    async def create_support_impersonation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.support_impersonation_requests[request["impersonation_request_id"]] = dict(request)
        return dict(request)

    async def append_audit_log(self, audit: dict[str, Any]) -> dict[str, Any]:
        self.audit_logs.append(dict(audit))
        return dict(audit)


def _service(store: FakeGovernanceStore) -> TenantGovernanceService:
    counters: dict[str, int] = {}
    now = datetime(2026, 5, 22, 15, 30, tzinfo=UTC)

    def _id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]:03d}"

    return TenantGovernanceService(store=store, id_factory=_id, clock=lambda: now)


def _platform_actor() -> GovernanceActor:
    return GovernanceActor(
        actor_user_id="user_platform_001",
        actor_membership_id=None,
        platform_role="platform_support",
        request_id="req_123",
        ip_address="203.0.113.10",
    )


def _academy_actor() -> GovernanceActor:
    return GovernanceActor(
        actor_user_id="user_admin_001",
        actor_membership_id="membership_admin_001",
        platform_role=None,
        request_id="req_456",
        ip_address="198.51.100.20",
    )


def _assert_required_audit_fields(
    audit: dict[str, Any],
    *,
    actor: GovernanceActor,
    academy_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
) -> None:
    assert audit["actor_user_id"] == actor.actor_user_id
    assert audit["actor_membership_id"] == actor.actor_membership_id
    assert audit["actor_platform_role"] == actor.platform_role
    assert audit["academy_id"] == academy_id
    assert audit["action"] == action
    assert audit["entity_type"] == entity_type
    assert audit["entity_id"] == entity_id
    assert "before_snapshot" in audit
    assert "after_snapshot" in audit
    assert audit["request_id"] == actor.request_id
    assert audit["ip_address"] == actor.ip_address
    assert audit["created_at"] == datetime(2026, 5, 22, 15, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_tenant_export_request_captures_retention_pii_and_audit() -> None:
    store = FakeGovernanceStore()
    service = _service(store)
    actor = _academy_actor()

    result = await service.request_tenant_export(
        RequestTenantExportCommand(
            academy_id="acad_001",
            actor=actor,
            include_pii=False,
            reason="customer admin download",
        )
    )

    assert result.export_request_id == "tenant_export_001"
    assert result.status == "queued"
    export = store.tenant_exports[result.export_request_id]
    assert export["academy_id"] == "acad_001"
    assert export["include_pii"] is False
    assert export["retention_policy"]["audit_log_retention_days"] == 2555
    assert export["pii_handling_policy"]["redact_exports_by_default"] is True
    assert export["pii_handling_policy"]["student_pii_fields"] == [
        "full_name",
        "date_of_birth",
        "medical_notes",
        "parent_contact",
    ]

    _assert_required_audit_fields(
        store.audit_logs[0],
        actor=actor,
        academy_id="acad_001",
        action="tenant_export.requested",
        entity_type="tenant_export_request",
        entity_id="tenant_export_001",
    )
    assert store.audit_logs[0]["before_snapshot"] is None
    assert store.audit_logs[0]["after_snapshot"]["status"] == "queued"


@pytest.mark.asyncio
async def test_tenant_deletion_request_uses_soft_delete_and_retention_policy() -> None:
    store = FakeGovernanceStore()
    service = _service(store)
    actor = _academy_actor()

    result = await service.request_tenant_deletion(
        RequestTenantDeletionCommand(
            academy_id="acad_001",
            actor=actor,
            reason="tenant owner requested account closure",
        )
    )

    assert result.deletion_request_id == "tenant_deletion_001"
    assert result.status == "pending_review"
    deletion = store.tenant_deletions[result.deletion_request_id]
    assert deletion["hard_delete_allowed"] is False
    assert deletion["soft_delete_policy"]["tenant_status_after_request"] == "deletion_requested"
    assert deletion["soft_delete_policy"]["preserve_audit_logs"] is True
    assert deletion["retention_policy"]["tenant_data_retention_days_after_deletion"] == 30
    assert deletion["retention_policy"]["financial_record_retention_days"] == 2555

    _assert_required_audit_fields(
        store.audit_logs[0],
        actor=actor,
        academy_id="acad_001",
        action="tenant_deletion.requested",
        entity_type="tenant_deletion_request",
        entity_id="tenant_deletion_001",
    )


@pytest.mark.asyncio
async def test_student_data_deletion_request_is_scoped_to_student_and_redaction_policy() -> None:
    store = FakeGovernanceStore()
    service = _service(store)
    actor = _academy_actor()

    result = await service.request_student_data_deletion(
        RequestStudentDataDeletionCommand(
            academy_id="acad_001",
            student_id="student_001",
            actor=actor,
            reason="parent erasure request",
        )
    )

    assert result.student_deletion_request_id == "student_deletion_001"
    assert result.status == "pending_review"
    request = store.student_deletions[result.student_deletion_request_id]
    assert request["academy_id"] == "acad_001"
    assert request["student_id"] == "student_001"
    assert request["delete_student_profile"] is False
    assert request["redact_student_pii"] is True
    assert request["pii_handling_policy"]["delete_minor_profile_without_review"] is False

    _assert_required_audit_fields(
        store.audit_logs[0],
        actor=actor,
        academy_id="acad_001",
        action="student_data_deletion.requested",
        entity_type="student_data_deletion_request",
        entity_id="student_deletion_001",
    )


@pytest.mark.asyncio
async def test_support_access_requires_platform_role_and_writes_complete_audit_log() -> None:
    store = FakeGovernanceStore()
    service = _service(store)
    actor = _platform_actor()

    result = await service.grant_support_access(
        GrantSupportAccessCommand(
            academy_id="acad_001",
            actor=actor,
            support_user_id="user_support_002",
            purpose="debug tenant onboarding",
            expires_in_hours=2,
        )
    )

    assert result.support_access_grant_id == "support_access_001"
    assert result.status == "active"
    grant = store.support_access_grants[result.support_access_grant_id]
    assert grant["support_user_id"] == "user_support_002"
    assert grant["purpose"] == "debug tenant onboarding"
    assert grant["expires_at"] == datetime(2026, 5, 22, 17, 30, tzinfo=UTC)

    _assert_required_audit_fields(
        store.audit_logs[0],
        actor=actor,
        academy_id="acad_001",
        action="support_access.granted",
        entity_type="support_access_grant",
        entity_id="support_access_001",
    )


@pytest.mark.asyncio
async def test_support_access_rejects_non_platform_actor_without_audit() -> None:
    store = FakeGovernanceStore()
    service = _service(store)

    with pytest.raises(GovernancePermissionDenied, match="platform support role required"):
        await service.grant_support_access(
            GrantSupportAccessCommand(
                academy_id="acad_001",
                actor=_academy_actor(),
                support_user_id="user_support_002",
                purpose="debug tenant onboarding",
            )
        )

    assert store.support_access_grants == {}
    assert store.audit_logs == []


@pytest.mark.asyncio
async def test_support_impersonation_is_conservative_and_audited_without_session() -> None:
    store = FakeGovernanceStore()
    service = _service(store)
    actor = _platform_actor()

    result = await service.request_support_impersonation(
        RequestSupportImpersonationCommand(
            academy_id="acad_001",
            actor=actor,
            target_user_id="user_parent_001",
            purpose="reproduce parent portal issue",
        )
    )

    assert result.impersonation_request_id == "support_impersonation_001"
    assert result.status == "requires_manual_approval"
    assert result.session_token is None
    request = store.support_impersonation_requests[result.impersonation_request_id]
    assert request["impersonation_enabled"] is False
    assert request["target_user_id"] == "user_parent_001"
    assert request["approval_required"] is True

    _assert_required_audit_fields(
        store.audit_logs[0],
        actor=actor,
        academy_id="acad_001",
        action="support_impersonation.requested",
        entity_type="support_impersonation_request",
        entity_id="support_impersonation_001",
    )
    assert store.audit_logs[0]["after_snapshot"]["impersonation_enabled"] is False


def test_default_governance_policies_document_launch_constraints() -> None:
    assert SoftDeletePolicy().tenant_status_after_request == "deletion_requested"
    assert SoftDeletePolicy().preserve_audit_logs is True
    assert RetentionPolicy().audit_log_retention_days == 2555
    assert RetentionPolicy().financial_record_retention_days == 2555
    assert PIIHandlingPolicy().redact_exports_by_default is True
    assert PIIHandlingPolicy().delete_minor_profile_without_review is False
