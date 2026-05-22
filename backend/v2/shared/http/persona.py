"""Persona enforcement dependency.

A request hitting `/api/v2/coach/...` must come from a user with the `coach`
role. Wrong-persona requests return **404** (never 403) per the security
matrix — so route existence is not leaked.

Usage in a coach route file::

    router = APIRouter(
        prefix="/coach",
        dependencies=[Depends(require_persona("coach"))],
    )
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import Depends, HTTPException

from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

Persona = Literal["coach", "parent", "admin"]


def require_persona(persona: Persona) -> Callable[..., AuthClaims]:
    """Return a FastAPI dependency that enforces the given persona.

    Returns the AuthClaims on success; raises 404 on persona mismatch.
    """

    async def _dep(claims: AuthClaims = Depends(get_auth_claims)) -> AuthClaims:
        if persona not in claims.roles:
            # 404, not 403: do not leak route existence.
            raise HTTPException(status_code=404, detail="Not found")
        return claims

    return _dep
