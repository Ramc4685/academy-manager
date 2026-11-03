"""Current-user BFF endpoint.

This keeps post-login routing tied to the same Firebase -> Mongo
authorization path as every persona BFF route.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.communications.application.use_cases.register_push_device import (
    MAX_APP_VERSION_LENGTH,
    MAX_TOKEN_LENGTH,
    PushPlatform,
    RegisterPushDevice,
    RegisterPushDeviceCommand,
)
from backend.v2.contexts.communications.application.use_cases.unregister_push_device import (
    UnregisterPushDevice,
)
from backend.v2.contexts.identity.application.list_my_memberships_use_case import (
    ListMyMembershipsUseCase,
)
from backend.v2.shared.auth.claims import AuthClaims, Role, get_auth_claims

router = APIRouter(tags=["auth"])


class MeResponse(BaseModel):
    user_id: str
    email: str
    academy_id: str
    roles: tuple[Role, ...]
    membership_id: str | None = None
    platform_roles: tuple[str, ...] = ()


@router.get("/me", response_model=MeResponse)
async def me(claims: AuthClaims = Depends(get_auth_claims)) -> MeResponse:
    return MeResponse(
        user_id=claims.user_id,
        email=claims.email,
        academy_id=claims.academy_id,
        roles=claims.roles,
        membership_id=claims.membership_id,
        platform_roles=tuple(str(r) for r in claims.platform_roles),
    )


class MembershipSummaryView(BaseModel):
    academy_id: str
    academy_name: str | None = None
    academy_slug: str | None = None
    roles: tuple[Role, ...]
    status: str
    is_default: bool


class MyMembershipsResponse(BaseModel):
    memberships: tuple[MembershipSummaryView, ...]
    active_academy_id: str


@router.get("/me/memberships", response_model=MyMembershipsResponse)
async def my_memberships(
    request: Request, claims: AuthClaims = Depends(get_auth_claims)
) -> MyMembershipsResponse:
    use_case: ListMyMembershipsUseCase = request.app.state.list_my_memberships
    output = await use_case.execute(user_id=claims.user_id, active_academy_id=claims.academy_id)
    return MyMembershipsResponse(
        memberships=tuple(
            MembershipSummaryView(
                academy_id=m.academy_id,
                academy_name=m.academy_name,
                academy_slug=m.academy_slug,
                roles=m.roles,
                status=m.status,
                is_default=m.is_default,
            )
            for m in output.memberships
        ),
        active_academy_id=output.active_academy_id,
    )


class RegisterDeviceRequest(BaseModel):
    token: str = Field(min_length=1, max_length=MAX_TOKEN_LENGTH)
    platform: PushPlatform
    app_version: str | None = Field(default=None, max_length=MAX_APP_VERSION_LENGTH)


class DeviceView(BaseModel):
    platform: PushPlatform
    app_version: str | None
    created_at: datetime
    last_seen_at: datetime


@router.post("/me/devices", response_model=DeviceView)
async def register_my_device(
    body: RegisterDeviceRequest,
    request: Request,
    claims: AuthClaims = Depends(get_auth_claims),
) -> DeviceView:
    """Register this app install for push (any persona). Idempotent."""
    use_case: RegisterPushDevice = request.app.state.register_push_device
    device = await use_case.execute(
        RegisterPushDeviceCommand(
            user_id=claims.user_id,
            token=body.token,
            platform=body.platform,
            app_version=body.app_version,
        )
    )
    return DeviceView(
        platform=device.platform,
        app_version=device.app_version,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
    )


@router.delete("/me/devices/{token}", status_code=204, response_model=None)
async def unregister_my_device(
    token: str,
    request: Request,
    claims: AuthClaims = Depends(get_auth_claims),
) -> None:
    """Drop the caller's token on logout; missing or not-yours is a silent no-op."""
    use_case: UnregisterPushDevice = request.app.state.unregister_push_device
    await use_case.execute(user_id=claims.user_id, token=token)
