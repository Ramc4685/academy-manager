"""Platform routes for SaaS tenant bootstrap."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
    BootstrapAcademyResult,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(prefix="/platform", tags=["platform.bootstrap"])


class BootstrapAcademyRequest(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    owner_email: EmailStr
    owner_display_name: str = Field(min_length=1)
    timezone: str = Field(default="UTC", min_length=1)


class BootstrapAcademyResponse(BaseModel):
    academy_id: str
    slug: str
    primary_domain: str
    owner_user_id: str
    membership_id: str
    owner_role: str
    created: bool
    default_records: tuple[str, ...]


async def require_platform_admin(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    if not claims.is_platform_admin():
        raise HTTPException(status_code=404, detail="Not found")
    return claims


def get_bootstrap_academy(request: Request) -> BootstrapAcademy:
    use_case = getattr(request.app.state, "bootstrap_academy", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Tenant bootstrap is not configured")
    return use_case  # type: ignore[no-any-return]


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
