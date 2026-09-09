"""Admin routes for placing/returning a hold (issue #697)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.enrollment-holds"])


class HoldEnrollmentRequest(BaseModel):
    return_on: date
    reason: str | None = None


class ReturnFromHoldRequest(BaseModel):
    reason: str | None = None


@router.post("/enrollments/{enrollment_id}/hold", status_code=204)
async def hold_enrollment(
    enrollment_id: str,
    body: HoldEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.hold_enrollment.execute(  # type: ignore[union-attr]
        enrollment_id,
        return_on=body.return_on,
        reason=body.reason,
        actor_id=claims.user_id,
    )


@router.post("/enrollments/{enrollment_id}/return", status_code=204)
async def return_from_hold(
    enrollment_id: str,
    body: ReturnFromHoldRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.return_from_hold.execute(  # type: ignore[union-attr]
        enrollment_id,
        reason=body.reason,
        actor_id=claims.user_id,
    )
