"""AuthClaims value object + FastAPI dependency placeholder.

The real loader lives in `contexts/identity/application/use_cases/load_auth_claims.py`
(landed in W1A-02). Phase 0 provides a placeholder dependency that raises 401
so routes can declare `Depends(get_auth_claims)` and tests can override it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

Role = Literal["admin", "coach", "parent"]


class AuthClaims(BaseModel, frozen=True):
    """Identity claims attached to an authenticated request.

    Produced by the Identity context's `load_auth_claims` use case (W1A-02).
    Carries the `academy_id` set by `TenancyMiddleware`.
    """

    user_id: str
    email: str
    academy_id: str
    roles: tuple[Role, ...] = Field(default_factory=tuple)

    def has_role(self, role: Role) -> bool:
        return role in self.roles


async def get_auth_claims(request: Request) -> AuthClaims:
    """Resolve AuthClaims from the request state.

    Real implementation lands in W1A-02; this Phase 0 placeholder reads
    `request.state.auth_claims` (set by middleware in W1A-02) and raises 401
    otherwise. Tests inject claims via FastAPI's dependency override.
    """
    claims: AuthClaims | None = getattr(request.state, "auth_claims", None)
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return claims
