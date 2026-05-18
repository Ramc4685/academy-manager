"""Admin pause request routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    DecidePauseRequestCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import AdminPauseRequestList, AdminPauseRequestView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.pause_requests"])


@router.get("/pause-requests", response_model=AdminPauseRequestList)
async def list_pause_requests(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPauseRequestList:
    rows = await use_cases.list_admin_pause_requests.execute()
    return AdminPauseRequestList(requests=[AdminPauseRequestView(**r.model_dump()) for r in rows])


@router.post("/pause-requests/{pause_request_id}/approve", response_model=AdminPauseRequestView)
async def approve_pause_request(
    pause_request_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPauseRequestView:
    row = await use_cases.approve_pause_request.execute(
        DecidePauseRequestCommand(pause_request_id=pause_request_id, admin_id=claims.user_id)
    )
    return AdminPauseRequestView(**row.model_dump())


@router.post("/pause-requests/{pause_request_id}/decline", response_model=AdminPauseRequestView)
async def decline_pause_request(
    pause_request_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPauseRequestView:
    row = await use_cases.decline_pause_request.execute(
        DecidePauseRequestCommand(pause_request_id=pause_request_id, admin_id=claims.user_id)
    )
    return AdminPauseRequestView(**row.model_dump())
