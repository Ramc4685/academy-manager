"""Cross-tenant visibility over the email suppression list (issue #556).

**Why this lives under /platform and not /admin.** The suppression list is keyed
on the email address alone and is deliberately NOT tenant-scoped: the Resend
sender domain is shared by every academy, so a bounce seen under academy A must
stop academy B. That makes the list a cross-tenant resource, and
``shared/auth/claims.py`` is explicit that academy-scoped ``roles`` must never
gate cross-tenant data — "cross-tenant capabilities live in ``platform_roles``".

Guarding this with ``require_persona("admin")`` (as the first cut did) would
hand any single tenant's admin the email addresses of every other academy's
parents and coaches, plus the fact that a named person filed a spam complaint,
and would let them release another tenant's hard bounce. Hence the platform
guards below, which 404 rather than 403 so the surface is not discoverable —
the idiom already used by ``audit_routes`` and ``governance_routes``.

A release is not permanent: the next bounce for the same address re-suppresses
it. Use cases are read off ``app.state`` because the suppression store is global
and has no per-academy composition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(prefix="/platform", tags=["platform-communications"])


async def require_platform_operator(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    """Read access: platform admin or platform support."""
    if not (claims.is_platform_admin() or claims.has_platform_role("platform_support")):
        raise HTTPException(status_code=404, detail="Not found")
    return claims


async def require_platform_admin(
    claims: AuthClaims = Depends(get_auth_claims),
) -> AuthClaims:
    """Write access: releasing an address is a mutation, so admin only."""
    if not claims.is_platform_admin():
        raise HTTPException(status_code=404, detail="Not found")
    return claims


class SuppressionView(BaseModel):
    email: str
    reason: str
    bounce_subtype: str | None
    provider: str
    first_seen_at: str
    last_seen_at: str


class SuppressionListResponse(BaseModel):
    suppressions: list[SuppressionView]


class ReleaseResponse(BaseModel):
    released: bool


@router.get("/communications/suppressions", response_model=SuppressionListResponse)
async def list_suppressions(
    request: Request,
    limit: int = 100,
    _claims: AuthClaims = Depends(require_platform_operator),
) -> SuppressionListResponse:
    use_case = getattr(request.app.state, "list_email_suppressions", None)
    if use_case is None:
        return SuppressionListResponse(suppressions=[])
    rows = await use_case.execute(limit=limit)
    return SuppressionListResponse(
        suppressions=[
            SuppressionView(
                email=row.email,
                reason=str(row.reason),
                bounce_subtype=row.bounce_subtype,
                provider=row.provider,
                first_seen_at=row.first_seen_at.isoformat(),
                last_seen_at=row.last_seen_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.post("/communications/suppressions/{email}/release", response_model=ReleaseResponse)
async def release_suppression(
    email: str,
    request: Request,
    claims: AuthClaims = Depends(require_platform_admin),
) -> ReleaseResponse:
    use_case = getattr(request.app.state, "release_email_suppression", None)
    if use_case is None:
        raise HTTPException(status_code=404, detail="Suppression list is not enabled")
    released = await use_case.execute(email=email, released_by=claims.user_id)
    return ReleaseResponse(released=released)
