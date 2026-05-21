"""AuthClaims value object + FastAPI dependency placeholder.

AuthClaims is the request-scoped, frozen projection of identity used by
routes and dependencies. It is constructed by the Identity context's
`load_auth_claims` use case after token verification, tenant resolution,
and `academy_memberships` lookup.

SaaS-shape (ADR-0007):

* `user_id`, `email`: who is signed in
* `academy_id`: the tenant the request is acting on (resolved from
  subdomain / custom domain — not inferred from the user)
* `membership_id`: id of the active `academy_memberships` row that proves
  this user has access to this academy
* `roles`: academy-scoped roles from that membership only
* `platform_roles`: cross-tenant capabilities (e.g. `platform_admin`),
  checked separately from `roles`

`membership_id` and `platform_roles` are optional so legacy single-tenant
callers (and the current `load_auth_claims` use case) can keep constructing
`AuthClaims(user_id=..., email=..., academy_id=..., roles=...)` until the
SaaS resolver lands; new SaaS code must populate them.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

# Re-exported from the identity domain so route files can import role types
# directly from the auth surface without crossing context boundaries.
Role = Literal["admin", "coach", "parent"]
PlatformRoleName = Literal["platform_admin", "platform_support"]


class AuthClaims(BaseModel, frozen=True):
    """Identity claims attached to an authenticated request.

    Produced by the Identity context's `load_auth_claims` use case after
    tenant resolution and membership validation. `roles` are scoped to
    `academy_id` only; cross-tenant capabilities live in `platform_roles`.
    """

    user_id: str
    email: str
    academy_id: str
    membership_id: str | None = None
    roles: tuple[Role, ...] = Field(default_factory=tuple)
    platform_roles: tuple[PlatformRoleName, ...] = Field(default_factory=tuple)

    def has_role(self, role: Role) -> bool:
        """Check an **academy-scoped** role for the current `academy_id`.

        Platform-wide capabilities are intentionally NOT checked here — use
        `has_platform_role` so callers cannot accidentally grant
        cross-tenant access through an academy-role guard.
        """

        return role in self.roles

    def has_platform_role(self, role: PlatformRoleName) -> bool:
        return role in self.platform_roles

    def is_platform_admin(self) -> bool:
        return "platform_admin" in self.platform_roles


async def get_auth_claims(request: Request) -> AuthClaims:
    """Resolve AuthClaims from the request state.

    Reads `request.state.auth_claims` set by `TenancyMiddleware` after the
    `load_auth_claims` use case verifies the bearer token. Raises 401 when
    no claims were attached (e.g. missing/invalid token on a protected
    route). Tests inject claims via FastAPI's dependency override.
    """

    claims: AuthClaims | None = getattr(request.state, "auth_claims", None)
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return claims
