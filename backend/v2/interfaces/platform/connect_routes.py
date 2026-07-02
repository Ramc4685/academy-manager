"""Platform Stripe Connect onboarding routes (Slice I).

Platform-admin BFF surface to start/refresh an academy's Connect onboarding.
Tenant is resolved EXPLICITLY from the path (``/academies/{academy_id}/...``),
never from ``default_academy_id`` or the caller's own academy. The route goes
through a composed use case (``app.state.platform_connect_onboarding``); it does
not import infrastructure or domain directly.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform", tags=["platform-connect"])


class ConnectOnboardingUseCase(Protocol):
    async def start(self, *, academy_id: str, refresh_url: str, return_url: str) -> dict: ...


class StartConnectOnboardingRequest(BaseModel):
    refresh_url: str = Field(min_length=1)
    return_url: str = Field(min_length=1)


class ConnectOnboardingResponse(BaseModel):
    academy_id: str
    stripe_account_id: str
    onboarding_url: str
    status: str


def get_connect_onboarding(request: Request) -> ConnectOnboardingUseCase:
    use_case = getattr(request.app.state, "platform_connect_onboarding", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Connect onboarding is not configured")
    return use_case  # type: ignore[no-any-return]


@router.post(
    "/academies/{academy_id}/connect/onboarding",
    response_model=ConnectOnboardingResponse,
    summary="Start or refresh an academy's Stripe Connect onboarding",
)
async def start_connect_onboarding(
    academy_id: str,
    payload: StartConnectOnboardingRequest,
    _: AuthClaims = Depends(require_platform_admin),
    use_case: ConnectOnboardingUseCase = Depends(get_connect_onboarding),
) -> ConnectOnboardingResponse:
    result = await use_case.start(
        academy_id=academy_id,
        refresh_url=payload.refresh_url,
        return_url=payload.return_url,
    )
    return ConnectOnboardingResponse(**result)
