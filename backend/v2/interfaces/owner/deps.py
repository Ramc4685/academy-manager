"""Owner BFF dependencies.

`require_owner` deliberately does NOT use `require_persona`. Persona checks
read `claims.roles`, which is scoped to the single academy the request
resolved to — an owner of academies A and B must be able to read the rollup
regardless of which of them the tenant header names. Scope therefore comes
from the caller's memberships, resolved inside the use case.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.v2.composition.owner import OwnerComposition
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims


def get_owner_use_cases(request: Request) -> OwnerComposition:
    composition = getattr(request.app.state, "owner", None)
    if composition is None:
        # Flag off / not wired: behave as if the surface does not exist.
        raise HTTPException(status_code=404, detail="Not found")
    return composition  # type: ignore[no-any-return]


async def require_owner(claims: AuthClaims = Depends(get_auth_claims)) -> AuthClaims:
    """Authenticate only. Ownership itself is enforced by the use case,
    which 404s when the caller owns no academies."""

    return claims
