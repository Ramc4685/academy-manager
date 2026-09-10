"""Admin routes for placing/returning a hold (issue #697)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.holds import (
    HoldEnrollment,
    ReturnFromHold,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.enrollment-holds"])


def _hold_enrollment(use_cases: AdminUseCases) -> HoldEnrollment:
    use_case = use_cases.hold_enrollment
    if use_case is None:
        raise HTTPException(status_code=503, detail="Enrollment holds are not configured")
    return use_case


def _return_from_hold(use_cases: AdminUseCases) -> ReturnFromHold:
    use_case = use_cases.return_from_hold
    if use_case is None:
        raise HTTPException(status_code=503, detail="Enrollment holds are not configured")
    return use_case


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
    await _hold_enrollment(use_cases).execute(
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
    await _return_from_hold(use_cases).execute(
        enrollment_id,
        reason=body.reason,
        actor_id=claims.user_id,
    )
