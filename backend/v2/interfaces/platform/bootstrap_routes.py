"""Platform routes for SaaS tenant bootstrap."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
    BootstrapAcademyResult,
)
from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    CreateTenantCommand,
    RecordAgreementAcceptanceCommand,
    TenantLifecycleService,
    UpdateTenantPlanCommand,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(prefix="/platform", tags=["platform"])


class BootstrapAcademyRequest(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    owner_email: EmailStr
    owner_display_name: str = Field(min_length=1)
    timezone: str = Field(min_length=1)


class BootstrapAcademyResponse(BaseModel):
    academy_id: str
    slug: str
    primary_domain: str
    owner_user_id: str
    membership_id: str
    owner_role: str
    created: bool
    default_records: tuple[str, ...]


class TenantLimitsPayload(BaseModel):
    max_students: int | None = Field(default=None, ge=0)
    max_coaches: int | None = Field(default=None, ge=0)
    max_locations: int | None = Field(default=None, ge=0)


class CreateTenantRequest(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    plan_code: str = Field(min_length=1)
    limits: TenantLimitsPayload = Field(default_factory=TenantLimitsPayload)


class TenantLifecycleResponse(BaseModel):
    academy_id: str
    display_name: str
    slug: str
    primary_domain: str
    status: str
    servable: bool
    reason: str | None = None
    plan_code: str
    limits: TenantLimitsPayload
    status_reason: str | None = None
    updated_by: str
    fee_model: str
    platform_agreement_version: str | None = None
    platform_agreement_accepted_at: datetime | None = None
    platform_agreement_accepted_by: str | None = None


class TenantHealthResponse(BaseModel):
    academy_id: str
    status: str
    servable: bool
    reason: str | None = None
    plan_code: str
    limits: TenantLimitsPayload


class LifecycleReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class RecordAgreementAcceptanceRequest(BaseModel):
    agreement_version: str = Field(min_length=1, max_length=64)
    # Free text by design (a name or an email): the signatory is whoever the
    # academy says signed, not necessarily an account holder. Only a platform
    # admin can write it; each write replaces the tenant's current acceptance
    # and the previous one is kept in the tenant.agreement_accepted audit row.
    accepted_by: str = Field(
        min_length=1,
        max_length=200,
        description="Academy signatory, free text (name or email).",
    )


class UpdateTenantPlanRequest(BaseModel):
    plan_code: str = Field(min_length=1)
    limits: TenantLimitsPayload = Field(default_factory=TenantLimitsPayload)


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


def get_bootstrap_academy(request: Request) -> BootstrapAcademy:
    use_case = getattr(request.app.state, "bootstrap_academy", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Tenant bootstrap is not configured")
    return use_case  # type: ignore[no-any-return]


def get_tenant_lifecycle(request: Request) -> TenantLifecycleService:
    use_case = getattr(request.app.state, "tenant_lifecycle", None)
    if use_case is not None:
        return use_case  # type: ignore[no-any-return]
    raise HTTPException(status_code=503, detail="Tenant lifecycle is not configured")


def _tenant_response(tenant) -> TenantLifecycleResponse:
    health = tenant.health()
    return TenantLifecycleResponse(
        academy_id=tenant.academy_id,
        display_name=tenant.display_name,
        slug=tenant.slug,
        primary_domain=tenant.primary_domain,
        status=tenant.status,
        servable=health.servable,
        reason=health.reason,
        plan_code=tenant.plan_code,
        limits=TenantLimitsPayload(**tenant.limits.model_dump()),
        status_reason=tenant.status_reason,
        updated_by=tenant.updated_by,
        fee_model=tenant.fee_model,
        platform_agreement_version=tenant.platform_agreement_version,
        platform_agreement_accepted_at=tenant.platform_agreement_accepted_at,
        platform_agreement_accepted_by=tenant.platform_agreement_accepted_by,
    )


@router.post("/academies/bootstrap", response_model=BootstrapAcademyResponse)
async def bootstrap_academy(
    payload: BootstrapAcademyRequest,
    _: AuthClaims = Depends(require_platform_admin),
    use_case: BootstrapAcademy = Depends(get_bootstrap_academy),
) -> BootstrapAcademyResponse:
    result: BootstrapAcademyResult = await use_case.execute(
        BootstrapAcademyCommand(**payload.model_dump())
    )
    return BootstrapAcademyResponse(**result.model_dump())


@router.post("/tenants", response_model=TenantLifecycleResponse)
async def create_tenant(
    payload: CreateTenantRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    tenant = await use_case.create_tenant(
        CreateTenantCommand(
            **payload.model_dump(),
            actor_user_id=claims.user_id,
        )
    )
    return _tenant_response(tenant)


@router.get("/tenants", response_model=list[TenantLifecycleResponse])
async def list_tenants(
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> list[TenantLifecycleResponse]:
    return [_tenant_response(tenant) for tenant in await use_case.list_tenants()]


@router.get("/tenants/{academy_id}/status", response_model=TenantLifecycleResponse)
async def get_tenant_status(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(await use_case.get_tenant(academy_id))


@router.get("/tenants/{academy_id}/health", response_model=TenantHealthResponse)
async def get_tenant_health(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_operator),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantHealthResponse:
    health = await use_case.get_tenant_health(academy_id)
    body = health.model_dump()
    body["limits"] = TenantLimitsPayload(**body["limits"])
    return TenantHealthResponse(**body)


@router.post("/tenants/{academy_id}/activate", response_model=TenantLifecycleResponse)
async def activate_tenant(
    academy_id: str,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(
        await use_case.activate_tenant(academy_id, actor_user_id=claims.user_id)
    )


@router.post("/tenants/{academy_id}/agreement", response_model=TenantLifecycleResponse)
async def record_agreement_acceptance(
    academy_id: str,
    payload: RecordAgreementAcceptanceRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    """Record the academy's acceptance of a platform agreement version (L9c)."""
    return _tenant_response(
        await use_case.record_agreement_acceptance(
            academy_id,
            RecordAgreementAcceptanceCommand(
                **payload.model_dump(),
                actor_user_id=claims.user_id,
            ),
        )
    )


@router.post("/tenants/{academy_id}/suspend", response_model=TenantLifecycleResponse)
async def suspend_tenant(
    academy_id: str,
    payload: LifecycleReasonRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(
        await use_case.suspend_tenant(
            academy_id,
            actor_user_id=claims.user_id,
            reason=payload.reason,
        )
    )


@router.post("/tenants/{academy_id}/cancel", response_model=TenantLifecycleResponse)
async def cancel_tenant(
    academy_id: str,
    payload: LifecycleReasonRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(
        await use_case.cancel_tenant(
            academy_id,
            actor_user_id=claims.user_id,
            reason=payload.reason,
        )
    )


@router.post("/tenants/{academy_id}/reactivate", response_model=TenantLifecycleResponse)
async def reactivate_tenant(
    academy_id: str,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(
        await use_case.reactivate_tenant(academy_id, actor_user_id=claims.user_id)
    )


@router.patch("/tenants/{academy_id}/plan", response_model=TenantLifecycleResponse)
async def update_tenant_plan(
    academy_id: str,
    payload: UpdateTenantPlanRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    use_case: TenantLifecycleService = Depends(get_tenant_lifecycle),
) -> TenantLifecycleResponse:
    return _tenant_response(
        await use_case.update_plan_limits(
            academy_id,
            UpdateTenantPlanCommand(
                **payload.model_dump(),
                actor_user_id=claims.user_id,
            ),
        )
    )
