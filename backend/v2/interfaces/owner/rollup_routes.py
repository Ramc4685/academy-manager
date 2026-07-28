"""Owner cross-academy financial rollup route (UIM11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.composition.owner import OwnerComposition
from backend.v2.contexts.billing.application.use_cases.owner_rollup import (
    NotAFranchiseOwner,
    OwnerRollup,
)
from backend.v2.interfaces.owner.deps import get_owner_use_cases
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims

router = APIRouter(tags=["owner.rollup"])


@router.get("/rollup", response_model=OwnerRollup)
async def owner_rollup(
    months: list[str] | None = Query(default=None, description="Filter to YYYY-MM months"),
    claims: AuthClaims = Depends(get_auth_claims),
    use_cases: OwnerComposition = Depends(get_owner_use_cases),
) -> OwnerRollup:
    try:
        return await use_cases.get_rollup.execute(
            user_id=claims.user_id,
            months=tuple(months) if months else None,
        )
    except NotAFranchiseOwner:
        # 404, not 403: do not leak that the owner surface exists.
        raise HTTPException(status_code=404, detail="Not found") from None
