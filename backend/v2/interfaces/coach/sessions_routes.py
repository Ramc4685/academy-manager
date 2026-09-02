"""GET /api/v2/coach/sessions — all upcoming sessions assigned to this coach.

A coach supervisor (academy admin/owner, #632) gets every upcoming
occurrence in the academy, each labelled with its coach.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.coach.deps import CoachUseCases, coach_names_for, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachScheduleEntry, CoachScheduleResponse
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach"])


@router.get(
    "/sessions",
    response_model=CoachScheduleResponse,
    summary="All upcoming sessions assigned to this coach",
)
async def get_sessions(
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachScheduleResponse:
    supervisor = is_coach_supervisor(claims)
    academy_wide = getattr(use_cases, "list_all_sessions_for_academy", None)
    if supervisor and academy_wide is not None:
        sessions = await academy_wide()
    else:
        sessions = await use_cases.list_all_sessions(claims.user_id)  # type: ignore[operator]
    coach_names = await coach_names_for(sessions, use_cases=use_cases, supervisor=supervisor)
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
                coach_id=getattr(s, "coach_id", None),
                coach_name=coach_names.get(getattr(s, "coach_id", None) or ""),
            )
            for s in sessions
        ]
    )
