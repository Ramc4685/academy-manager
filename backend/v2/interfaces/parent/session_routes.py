"""Parent session catalog routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentAvailableSessionsResponse,
    ParentAvailableSessionView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.sessions"])


@router.get(
    "/sessions/available",
    response_model=ParentAvailableSessionsResponse,
    summary="Parent-safe session catalog for onboarding",
)
async def list_available_sessions(
    _: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAvailableSessionsResponse:
    sessions = await use_cases.list_available_sessions.execute()
    return ParentAvailableSessionsResponse(
        sessions=[
            ParentAvailableSessionView(
                session_id=s.session_id,
                title=s.title,
                location=s.location,
                start_at=s.start_at,
                end_at=s.end_at,
                capacity=s.capacity,
                enrolled_count=s.enrolled_count,
                available_seats=s.available_seats,
                amount_cents=s.amount_cents,
            )
            for s in sessions
        ]
    )
