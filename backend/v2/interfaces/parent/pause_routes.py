"""Parent pause request routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    RequestEnrollmentPauseCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    CreatePauseRequest,
    PauseRequestsResponse,
    PauseRequestView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.pause_requests"])


@router.get("/pause-requests", response_model=PauseRequestsResponse)
async def list_pause_requests(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> PauseRequestsResponse:
    rows = await use_cases.list_parent_pause_requests.execute(claims.user_id)
    return PauseRequestsResponse(requests=[PauseRequestView(**r.model_dump()) for r in rows])


@router.post("/pause-requests", response_model=PauseRequestView)
async def create_pause_request(
    body: CreatePauseRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> PauseRequestView:
    row = await use_cases.request_enrollment_pause.execute(
        RequestEnrollmentPauseCommand(
            parent_id=claims.user_id,
            enrollment_id=body.enrollment_id,
            period=body.period,
            reason=body.reason,
        )
    )
    return PauseRequestView(**row.model_dump())
