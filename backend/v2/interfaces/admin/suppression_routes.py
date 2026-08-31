"""Admin visibility over the email suppression list (issue #556).

The list is global (one shared sender domain), so this surface is read-mostly:
an admin can see which addresses the provider reported dead or complaining, and
release one they believe was suppressed in error. A release is not permanent —
the next bounce for the same address re-suppresses it.

Use cases are read off ``app.state`` rather than threaded through
``AdminUseCases`` because the suppression store is not tenant-scoped and has no
per-academy composition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(prefix="/communications", tags=["admin.communications"])


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


@router.get("/suppressions", response_model=SuppressionListResponse)
async def list_suppressions(
    request: Request,
    limit: int = 100,
    _claims: AuthClaims = Depends(require_persona("admin")),
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


@router.post("/suppressions/{email}/release", response_model=ReleaseResponse)
async def release_suppression(
    email: str,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
) -> ReleaseResponse:
    use_case = getattr(request.app.state, "release_email_suppression", None)
    if use_case is None:
        raise HTTPException(status_code=404, detail="Suppression list is not enabled")
    released = await use_case.execute(email=email, released_by=claims.user_id)
    return ReleaseResponse(released=released)
