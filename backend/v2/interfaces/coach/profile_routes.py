"""GET/PATCH /api/v2/coach/profile — self-service profile for coaches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachAcademyContactView,
    CoachPayResponse,
    CoachProfileResponse,
    UpdateCoachProfileRequest,
)
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


@router.get(
    "/profile/pay",
    response_model=CoachPayResponse,
    summary="The current coach's classes taught and approved or paid payslip",
)
async def get_my_pay(
    response: Response,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachPayResponse:
    """Self only (D-05). The coach is always ``claims.user_id``: there is no
    parameter naming a coach, so no URL can return someone else's pay."""
    if use_cases.get_coach_pay is None:
        raise HTTPException(status_code=404, detail="Not found")
    summary = await use_cases.get_coach_pay.execute(  # type: ignore[attr-defined]
        academy_id=claims.academy_id, coach_id=claims.user_id, month=month
    )
    info: dict[str, object] = {}
    if use_cases.get_academy_info is not None:
        info = await use_cases.get_academy_info(academy_id=claims.academy_id)  # type: ignore[operator]
    response.headers["Cache-Control"] = "no-store"
    return CoachPayResponse(
        **summary.model_dump(),
        academy_contact=CoachAcademyContactView(
            name=str(info.get("name") or "Your academy"),
            phone=info.get("contact_phone") or None,  # type: ignore[arg-type]
            email=info.get("contact_email") or None,  # type: ignore[arg-type]
        ),
    )
