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

from backend.v2.shared.http.errors import DomainError

# Re-exported from the identity domain so route files can import role types
# directly from the auth surface without crossing context boundaries. Kept
# in sync by hand with `contexts.identity.domain.models.Role` (shared/ must
# not import contexts/ — that would invert the dependency direction) —
# when a role is added there, it must be added here too, or membership rows
# holding it fail to deserialize into AuthClaims (see UIM12 postmortem).
Role = Literal["admin", "coach", "assistant_coach", "parent", "student", "owner"]
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


class NotAuthenticated(DomainError, HTTPException):
    """401 raised when a protected route has no attached AuthClaims.

    When `TenancyMiddleware` swallowed a concrete auth failure it stashes the
    domain error *code* on `request.state.auth_error_code`; that code is
    surfaced here as `details.reason` so the login surface can tell the user
    why sign-in bounced (issue #425). Only the machine-readable code is ever
    exposed — never the underlying exception message.

    It is also an `HTTPException` so that apps which never registered the
    `DomainError` handler (test harnesses mounting a single router) still
    answer 401 rather than raising. `DomainError` precedes `HTTPException`
    in the MRO, so the richer envelope wins wherever the handler is
    registered — which includes the real app.
    """

    code = "Auth.NotAuthenticated"
    status_code = 401

    def __init__(self, message: str = "", **details: object) -> None:
        # `DomainError.__init__` is deliberately not delegated to: its
        # `super().__init__(message)` would land on `HTTPException` through
        # this class's MRO and be read as a status code. The two fields it
        # sets are assigned directly instead.
        HTTPException.__init__(self, status_code=self.status_code, detail=message or self.code)
        self.message = message or self.code
        self.details = details


async def get_auth_claims(request: Request) -> AuthClaims:
    """Resolve AuthClaims from the request state.

    Reads `request.state.auth_claims` set by `TenancyMiddleware` after the
    `load_auth_claims` use case verifies the bearer token. Raises 401 when
    no claims were attached (e.g. missing/invalid token on a protected
    route), carrying the middleware's failure code as `details.reason`.
    Tests inject claims via FastAPI's dependency override.
    """

    claims: AuthClaims | None = getattr(request.state, "auth_claims", None)
    if claims is None:
        reason = getattr(request.state, "auth_error_code", None)
        if reason:
            raise NotAuthenticated("Not authenticated", reason=reason)
        raise NotAuthenticated("Not authenticated")
    return claims
