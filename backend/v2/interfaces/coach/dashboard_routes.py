"""Coach dashboard metrics route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachDashboardResponse
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach.dashboard"])


@router.get("/dashboard", response_model=CoachDashboardResponse)
async def get_dashboard(
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachDashboardResponse:
    data = await use_cases.get_dashboard_metrics(claims.user_id)  # type: ignore[operator]
    return CoachDashboardResponse(**data)
