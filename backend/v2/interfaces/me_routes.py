"""Current-user BFF endpoint.

This keeps post-login routing tied to the same Firebase -> Mongo
authorization path as every persona BFF route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

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
