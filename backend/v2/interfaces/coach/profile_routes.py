"""GET/PATCH /api/v2/coach/profile — self-service profile for coaches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachProfileResponse, UpdateCoachProfileRequest
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_surface

router = APIRouter(tags=["coach"])


@router.get(
    "/profile",
    response_model=CoachProfileResponse,
    summary="Get the current coach's profile",
)
async def get_profile(
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachProfileResponse:
    profile = await use_cases.get_profile(claims.user_id)  # type: ignore[operator]
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.patch(
    "/profile",
    response_model=CoachProfileResponse,
    summary="Update the current coach's display name, phone, or email",
)
async def update_profile(
    body: UpdateCoachProfileRequest,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachProfileResponse:
    profile = await use_cases.update_profile(  # type: ignore[operator]
        claims.user_id, body, academy_id=claims.academy_id
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile
