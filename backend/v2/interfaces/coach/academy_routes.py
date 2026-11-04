"""GET /api/v2/coach/academy — the coach shell's academy mark (row 14).

Deliberately the narrowest read in the coach BFF: name, logo and brand colour
only, for the request academy (`AuthClaims.academy_id`, stamped per-request
by `require_coach_surface`, never a boot-time tenant). Everything else about
the academy profile is admin/owner territory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachAcademyView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_surface

router = APIRouter(tags=["coach.academy"])


@router.get(
    "/academy",
    response_model=CoachAcademyView,
    summary="The coach shell's academy mark (name, logo, brand colour)",
)
async def get_academy(
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachAcademyView:
    info = await use_cases.get_academy_info(academy_id=claims.academy_id)  # type: ignore[operator]
    return CoachAcademyView(**info)
