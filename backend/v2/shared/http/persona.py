"""Persona enforcement dependency.

A request hitting `/api/v2/coach/...` must come from a user with the `coach`
role. Wrong-persona requests return **404** (never 403) per the security
matrix — so route existence is not leaked.

Usage in a coach route file::

    router = APIRouter(
        prefix="/coach",
        dependencies=[Depends(require_persona("coach"))],
    )

The coach BFF is also a *supervision surface*: an academy ``admin`` or
``owner`` may use it to cover any session (see
``docs/superpowers/specs/2026-09-02-admin-coach-coverage-design.md``).
Coach route files use :func:`require_coach_surface` for that; every other
persona surface keeps the strict :func:`require_persona` guard.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import Depends, HTTPException

from backend.v2.shared.auth.claims import AuthClaims, Role, get_auth_claims

Persona = Literal["coach", "parent", "admin", "student"]

# Academy-scoped roles that may act on the coach surface for *any* session.
# Platform roles are deliberately excluded: cross-tenant capability never
# grants tenant-level coaching access.
COACH_SUPERVISOR_ROLES: tuple[Role, ...] = ("admin", "owner")


def is_coach_supervisor(claims: AuthClaims) -> bool:
    """True when the caller may cover any session on the coach surface.

    Derived only from the academy-scoped ``roles`` of the current tenant, so
    a supervisor in one academy is an ordinary user everywhere else.
    """

    return any(role in claims.roles for role in COACH_SUPERVISOR_ROLES)


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


def require_coach_surface() -> Callable[..., Awaitable[AuthClaims]]:
    """Dependency for coach BFF routes: admits coaches and coach supervisors.

    Parents, students, and anyone without an academy role still get 404,
    exactly like ``require_persona("coach")``. Routes that need to know
    whether the caller is covering (rather than assigned) call
    :func:`is_coach_supervisor` on the returned claims.
    """

    async def _dep(claims: AuthClaims = Depends(get_auth_claims)) -> AuthClaims:
        if "coach" not in claims.roles and not is_coach_supervisor(claims):
            raise HTTPException(status_code=404, detail="Not found")
        return claims

    return _dep
