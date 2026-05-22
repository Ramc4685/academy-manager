"""Current-user BFF endpoint.

This keeps post-login routing tied to the same Firebase -> Mongo
authorization path as every persona BFF route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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
