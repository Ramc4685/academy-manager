"""GET /api/v2/coach/sessions — all upcoming sessions assigned to this coach."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachScheduleEntry, CoachScheduleResponse
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach"])


@router.get(
    "/sessions",
    response_model=CoachScheduleResponse,
    summary="All upcoming sessions assigned to this coach",
)
async def get_sessions(
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachScheduleResponse:
    sessions = await use_cases.list_all_sessions(claims.user_id)  # type: ignore[operator]
    return CoachScheduleResponse(
        sessions=[
            CoachScheduleEntry(
                session_id=s.session_id,
                occurrence_id=s.occurrence_id,
                title=s.title,
                location=s.location,
                timezone=s.timezone,
                start_at=s.start_at,
                end_at=s.end_at,
            )
            for s in sessions
        ]
    )
