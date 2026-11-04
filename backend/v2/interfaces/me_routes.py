"""Current-user BFF endpoint.

This keeps post-login routing tied to the same Firebase -> Mongo
authorization path as every persona BFF route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    ForgetPushDevices,
    UnregisterPushDevice,
)
from backend.v2.contexts.identity.application.list_my_memberships_use_case import (
    ListMyMembershipsUseCase,
)
from backend.v2.contexts.identity.application.use_cases.request_account_deletion import (
    RequestAccountDeletion,
    RequestAccountDeletionCommand,
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


class AccountDeletionBody(BaseModel):
    # The typed confirmation from the delete screen; anything else is a 422.
    confirm: Literal["DELETE"]


class AccountDeletionView(BaseModel):
    status: str
    requested_at: datetime
    execute_after: datetime


@router.post("/me/account-deletion", response_model=AccountDeletionView)
async def request_my_account_deletion(
    body: AccountDeletionBody,
    request: Request,
    claims: AuthClaims = Depends(get_auth_claims),
) -> AccountDeletionView:
    """Delete the caller's own account (any persona; store rules, mobile M5).

    Needs a sign-in from the last few minutes. Locks the account in every
    academy at once and schedules the data clean-up; a repeat returns the
    request already on file.
    """
    use_case: RequestAccountDeletion = request.app.state.request_account_deletion
    deletion = await use_case.execute(
        RequestAccountDeletionCommand(
            user_id=claims.user_id, email=claims.email, signed_in_at=claims.signed_in_at
        )
    )
    forget: ForgetPushDevices = request.app.state.forget_push_devices
    await forget.execute(user_ids=deletion.aliases, academy_ids=deletion.academy_ids)
    return AccountDeletionView(
        status=deletion.status,
        requested_at=deletion.requested_at,
        execute_after=deletion.execute_after,
    )
