"""SaaS tenant governance domain models.

These models capture policy decisions only. They do not perform tenant data
mutation, billing changes, or support impersonation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PlatformGovernanceRole = Literal["platform_admin", "platform_support"]

TenantExportStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
DeletionRequestStatus = Literal["pending_review", "approved", "rejected", "completed"]
SupportAccessStatus = Literal["active", "expired", "revoked"]
SupportImpersonationStatus = Literal["requires_manual_approval", "rejected", "approved"]


class GovernanceActor(BaseModel):
    """Actor metadata required for platform/support audit rows."""

    model_config = {"frozen": True}

    actor_user_id: str = Field(min_length=1)
    actor_membership_id: str | None = None
    platform_role: PlatformGovernanceRole | None = None
    request_id: str = Field(min_length=1)
    ip_address: str | None = None

    @model_validator(mode="after")
    def _has_membership_or_platform_role(self) -> GovernanceActor:
        if self.actor_membership_id is None and self.platform_role is None:
            raise ValueError("actor_membership_id or platform_role is required")
        return self

    def has_platform_support_access(self) -> bool:
        return self.platform_role in {"platform_admin", "platform_support"}


class SoftDeletePolicy(BaseModel):
    """Default SaaS soft-delete stance.

    Tenant and student deletion workflows start as reviewed requests. Hard
    deletion is intentionally not performed by these application use cases.
    """

    model_config = {"frozen": True}

    tenant_status_after_request: str = "deletion_requested"
    student_status_after_request: str = "deletion_requested"
    preserve_audit_logs: bool = True
    preserve_financial_records: bool = True
    hard_delete_allowed: bool = False


class RetentionPolicy(BaseModel):
    """Minimum retention windows used by early SaaS governance."""

    model_config = {"frozen": True}

    tenant_data_retention_days_after_deletion: int = 30
    export_artifact_retention_days: int = 7
    audit_log_retention_days: int = 2555
    financial_record_retention_days: int = 2555
    support_access_audit_retention_days: int = 2555


class PIIHandlingPolicy(BaseModel):
    """PII handling defaults for exports and deletion requests."""

    model_config = {"frozen": True}

    redact_exports_by_default: bool = True
    delete_minor_profile_without_review: bool = False
    student_pii_fields: list[str] = Field(
        default_factory=lambda: [
            "full_name",
            "date_of_birth",
            "medical_notes",
            "parent_contact",
        ]
    )
    parent_pii_fields: list[str] = Field(
        default_factory=lambda: ["full_name", "email", "phone", "billing_contact"]
    )


class GovernanceAuditLog(BaseModel):
    """Audit row required for platform and support access."""

    model_config = {"frozen": True}

    audit_id: str
    actor_user_id: str
    actor_membership_id: str | None = None
    actor_platform_role: PlatformGovernanceRole | None = None
    academy_id: str
    action: str
    entity_type: str
    entity_id: str
    before_snapshot: dict[str, object] | None = None
    after_snapshot: dict[str, object] | None = None
    request_id: str
    ip_address: str | None = None
    created_at: datetime


class GovernanceRequestStatus(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    request_type: str
    academy_id: str
    status: str


class TenantExportRequest(BaseModel):
    model_config = {"frozen": True}

    export_request_id: str
    academy_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: TenantExportStatus = "queued"
    include_pii: bool = False
    reason: str
    retention_policy: dict[str, object]
    pii_handling_policy: dict[str, object]
    artifact_metadata: dict[str, object] | None = None
    artifact_expires_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    created_at: datetime


class TenantDeletionRequest(BaseModel):
    model_config = {"frozen": True}

    deletion_request_id: str
    academy_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: DeletionRequestStatus = "pending_review"
    reason: str
    hard_delete_allowed: bool = False
    soft_delete_policy: dict[str, object]
    retention_policy: dict[str, object]
    created_at: datetime


class StudentDataDeletionRequest(BaseModel):
    model_config = {"frozen": True}

    student_deletion_request_id: str
    academy_id: str
    student_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: DeletionRequestStatus = "pending_review"
    reason: str
    delete_student_profile: bool = False
    redact_student_pii: bool = True
    soft_delete_policy: dict[str, object]
    retention_policy: dict[str, object]
    pii_handling_policy: dict[str, object]
    created_at: datetime


class SupportAccessGrant(BaseModel):
    model_config = {"frozen": True}

    support_access_grant_id: str
    academy_id: str
    support_user_id: str
    granted_by_user_id: str
    granted_by_platform_role: PlatformGovernanceRole
    status: SupportAccessStatus = "active"
    purpose: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: str | None = None
    revoke_reason: str | None = None

    @field_validator("purpose")
    @classmethod
    def _strip_purpose(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("purpose is required")
        return stripped


class SupportImpersonationRequest(BaseModel):
    model_config = {"frozen": True}

    impersonation_request_id: str
    academy_id: str
    target_user_id: str
    requested_by_user_id: str
    requested_by_platform_role: PlatformGovernanceRole
    status: SupportImpersonationStatus = "requires_manual_approval"
    purpose: str
    impersonation_enabled: bool = False
    approval_required: bool = True
    session_token: str | None = None
    created_at: datetime
