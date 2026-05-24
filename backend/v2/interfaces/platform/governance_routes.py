"""Platform governance and support access routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.platform.governance.application.use_cases import (
    GrantSupportAccessCommand,
    RequestStudentDataDeletionCommand,
    RequestSupportImpersonationCommand,
    RequestTenantDeletionCommand,
    RequestTenantExportCommand,
    RevokeSupportAccessCommand,
    TenantGovernanceService,
)
from backend.v2.contexts.platform.governance.domain.models import GovernanceActor
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(prefix="/platform/governance", tags=["platform-governance"])


class TenantExportRequestPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    include_pii: bool = False


class TenantDeletionRequestPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class StudentDataDeletionRequestPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SupportAccessGrantPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    support_user_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    expires_in_hours: int = Field(default=4, ge=1, le=24)


class RevokeSupportAccessPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SupportImpersonationRequestPayload(BaseModel):
    academy_id: str = Field(min_length=1)
    target_user_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class TenantExportResponse(BaseModel):
    export_request_id: str
    academy_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: str
    include_pii: bool
    reason: str
    retention_policy: dict[str, object]
    pii_handling_policy: dict[str, object]
    artifact_metadata: dict[str, object] | None = None
    artifact_expires_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None
    created_at: datetime


class TenantDeletionResponse(BaseModel):
    deletion_request_id: str
    academy_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: str
    reason: str
    hard_delete_allowed: bool
    soft_delete_policy: dict[str, object]
    retention_policy: dict[str, object]
    created_at: datetime


class StudentDataDeletionResponse(BaseModel):
    student_deletion_request_id: str
    academy_id: str
    student_id: str
    requested_by_user_id: str
    requested_by_membership_id: str | None = None
    status: str
    reason: str
    delete_student_profile: bool
    redact_student_pii: bool
    soft_delete_policy: dict[str, object]
    retention_policy: dict[str, object]
    pii_handling_policy: dict[str, object]
    created_at: datetime


class SupportAccessGrantResponse(BaseModel):
    support_access_grant_id: str
    academy_id: str
    support_user_id: str
    granted_by_user_id: str
    granted_by_platform_role: str
    status: str
    purpose: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: str | None = None
    revoke_reason: str | None = None


class SupportImpersonationResponse(BaseModel):
    impersonation_request_id: str
    academy_id: str
    target_user_id: str
    requested_by_user_id: str
    requested_by_platform_role: str
    status: str
    purpose: str
    impersonation_enabled: bool
    approval_required: bool
    session_token: str | None = None
    created_at: datetime


class RequestStatusResponse(BaseModel):
    request_id: str
    request_type: str
    academy_id: str
    status: str


async def require_platform_admin(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    if not claims.is_platform_admin():
        raise HTTPException(status_code=404, detail="Not found")
    return claims


async def require_platform_operator(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    if not (claims.is_platform_admin() or claims.has_platform_role("platform_support")):
        raise HTTPException(status_code=404, detail="Not found")
    return claims


async def require_platform_support(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    if not (claims.is_platform_admin() or claims.has_platform_role("platform_support")):
        raise HTTPException(status_code=404, detail="Not found")
    return claims


def get_tenant_governance(request: Request) -> TenantGovernanceService:
    use_case = getattr(request.app.state, "tenant_governance", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Tenant governance is not configured")
    platform_audit = getattr(request.app.state, "platform_audit", None)
    if platform_audit is not None and getattr(use_case, "_audit_recorder", None) is None:
        use_case.configure_audit_recorder(platform_audit.record_event)
    return use_case  # type: ignore[no-any-return]


def _actor_from_claims(claims: AuthClaims, request: Request) -> GovernanceActor:
    role = _platform_role(claims)
    request_id = request.headers.get("x-request-id") or getattr(
        request.state, "request_id", "unknown"
    )
    client_host = request.client.host if request.client else None
    return GovernanceActor(
        actor_user_id=claims.user_id,
        actor_membership_id=claims.membership_id,
        platform_role=role,
        request_id=request_id,
        ip_address=client_host,
    )


def _platform_role(claims: AuthClaims) -> str | None:
    if claims.is_platform_admin():
        return "platform_admin"
    if claims.has_platform_role("platform_support"):
        return "platform_support"
    return None


@router.post("/tenant-exports", response_model=TenantExportResponse)
async def create_tenant_export_request(
    payload: TenantExportRequestPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> TenantExportResponse:
    result = await use_case.request_tenant_export(
        RequestTenantExportCommand(
            academy_id=payload.academy_id,
            actor=_actor_from_claims(claims, request),
            reason=payload.reason,
            include_pii=payload.include_pii,
        )
    )
    return TenantExportResponse(**result.model_dump())


@router.get("/tenant-exports", response_model=list[TenantExportResponse])
async def list_tenant_export_requests(
    academy_id: str | None = Query(default=None),
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> list[TenantExportResponse]:
    return _responses(
        await use_case.list_tenant_export_requests(academy_id=academy_id),
        TenantExportResponse,
    )


@router.post("/tenant-deletions", response_model=TenantDeletionResponse)
async def create_tenant_deletion_request(
    payload: TenantDeletionRequestPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> TenantDeletionResponse:
    result = await use_case.request_tenant_deletion(
        RequestTenantDeletionCommand(
            academy_id=payload.academy_id,
            actor=_actor_from_claims(claims, request),
            reason=payload.reason,
        )
    )
    return TenantDeletionResponse(**result.model_dump())


@router.get("/tenant-deletions", response_model=list[TenantDeletionResponse])
async def list_tenant_deletion_requests(
    academy_id: str | None = Query(default=None),
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> list[TenantDeletionResponse]:
    return _responses(
        await use_case.list_tenant_deletion_requests(academy_id=academy_id),
        TenantDeletionResponse,
    )


@router.post("/student-data-deletions", response_model=StudentDataDeletionResponse)
async def create_student_data_deletion_request(
    payload: StudentDataDeletionRequestPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> StudentDataDeletionResponse:
    result = await use_case.request_student_data_deletion(
        RequestStudentDataDeletionCommand(
            academy_id=payload.academy_id,
            student_id=payload.student_id,
            actor=_actor_from_claims(claims, request),
            reason=payload.reason,
        )
    )
    return StudentDataDeletionResponse(**result.model_dump())


@router.get("/student-data-deletions", response_model=list[StudentDataDeletionResponse])
async def list_student_data_deletion_requests(
    academy_id: str | None = Query(default=None),
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> list[StudentDataDeletionResponse]:
    return _responses(
        await use_case.list_student_data_deletion_requests(academy_id=academy_id),
        StudentDataDeletionResponse,
    )


@router.post("/support-access-grants", response_model=SupportAccessGrantResponse)
async def create_support_access_grant(
    payload: SupportAccessGrantPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> SupportAccessGrantResponse:
    result = await use_case.grant_support_access(
        GrantSupportAccessCommand(
            academy_id=payload.academy_id,
            actor=_actor_from_claims(claims, request),
            support_user_id=payload.support_user_id,
            purpose=payload.purpose,
            expires_in_hours=payload.expires_in_hours,
        )
    )
    return SupportAccessGrantResponse(**result.model_dump())


@router.get("/support-access-grants", response_model=list[SupportAccessGrantResponse])
async def list_support_access_grants(
    academy_id: str | None = Query(default=None),
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> list[SupportAccessGrantResponse]:
    return _responses(
        await use_case.list_support_access_grants(academy_id=academy_id),
        SupportAccessGrantResponse,
    )


@router.post(
    "/support-access-grants/{support_access_grant_id}/revoke",
    response_model=SupportAccessGrantResponse,
)
async def revoke_support_access_grant(
    support_access_grant_id: str,
    payload: RevokeSupportAccessPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> SupportAccessGrantResponse:
    result = await use_case.revoke_support_access(
        RevokeSupportAccessCommand(
            academy_id=payload.academy_id,
            actor=_actor_from_claims(claims, request),
            support_access_grant_id=support_access_grant_id,
            reason=payload.reason,
        )
    )
    return SupportAccessGrantResponse(**result.model_dump())


@router.post(
    "/support-impersonation-requests",
    response_model=SupportImpersonationResponse,
)
async def create_support_impersonation_request(
    payload: SupportImpersonationRequestPayload,
    request: Request,
    claims: AuthClaims = Depends(require_platform_support),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> SupportImpersonationResponse:
    result = await use_case.request_support_impersonation(
        RequestSupportImpersonationCommand(
            academy_id=payload.academy_id,
            actor=_actor_from_claims(claims, request),
            target_user_id=payload.target_user_id,
            purpose=payload.purpose,
        )
    )
    return SupportImpersonationResponse(**result.model_dump())


@router.get(
    "/support-impersonation-requests",
    response_model=list[SupportImpersonationResponse],
)
async def list_support_impersonation_requests(
    academy_id: str | None = Query(default=None),
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> list[SupportImpersonationResponse]:
    return _responses(
        await use_case.list_support_impersonation_requests(academy_id=academy_id),
        SupportImpersonationResponse,
    )


@router.get("/requests/{request_id}/status", response_model=RequestStatusResponse)
async def get_request_status(
    request_id: str,
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantGovernanceService = Depends(get_tenant_governance),
) -> RequestStatusResponse:
    return RequestStatusResponse(**(await use_case.get_request_status(request_id)).model_dump())


def _responses(items: list[Any], model: type[BaseModel]) -> list[Any]:
    return [model(**item.model_dump()) for item in items]
