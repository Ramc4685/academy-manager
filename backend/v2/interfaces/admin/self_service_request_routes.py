"""Admin routes for reviewing parent self-service requests (R2).

Covers the admin absence-notice queue plus makeup-request review
(list/approve/deny). Approval has NO billing dependency — the student
already paid for the missed session; see the use case docstring in
``makeup_requests.py`` for the BILLING SAFETY constraint.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ApproveMakeupRequestCommand,
    DenyMakeupRequestCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.self-service-requests"])


class MakeupRequestAdminRow(BaseModel):
    request_id: str
    student_id: str
    missed_occurrence_id: str
    requested_target_occurrence_id: str | None
    status: str
    expires_at: datetime
    denial_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    approved_target_occurrence_id: str | None
    created_at: datetime
    student_full_name: str | None


class MakeupRequestsAdminResponse(BaseModel):
    makeups: list[MakeupRequestAdminRow]


class AbsenceNoticeAdminRow(BaseModel):
    notice_id: str
    student_id: str
    occurrence_id: str
    session_id: str
    submitted_by: str
    submitted_at: datetime
    notice_window_met: bool
    student_full_name: str | None


class AbsencesAdminResponse(BaseModel):
    absences: list[AbsenceNoticeAdminRow]


class ApproveMakeupRequestBody(BaseModel):
    target_occurrence_id: str


class DenyMakeupRequestBody(BaseModel):
    reason: str


@router.get("/self-service/absences", response_model=AbsencesAdminResponse)
async def list_absences_for_admin(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AbsencesAdminResponse:
    rows = await use_cases.list_absences_for_admin.execute()
    return AbsencesAdminResponse(
        absences=[AbsenceNoticeAdminRow(**row.model_dump()) for row in rows]
    )


@router.get("/self-service/makeups", response_model=MakeupRequestsAdminResponse)
async def list_makeups_for_admin(
    status: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> MakeupRequestsAdminResponse:
    rows = await use_cases.list_makeup_requests_for_admin.execute(status)
    return MakeupRequestsAdminResponse(
        makeups=[MakeupRequestAdminRow(**row.model_dump()) for row in rows]
    )


@router.post(
    "/self-service/makeups/{request_id}/approve",
    response_model=MakeupRequestAdminRow,
)
async def approve_makeup_request(
    request_id: str,
    body: ApproveMakeupRequestBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> MakeupRequestAdminRow:
    request = await use_cases.approve_makeup_request.execute(
        ApproveMakeupRequestCommand(
            request_id=request_id,
            actor_id=claims.user_id,
            target_occurrence_id=body.target_occurrence_id,
        )
    )
    return MakeupRequestAdminRow(
        **request.model_dump(exclude={"academy_id", "parent_id"}),
        student_full_name=None,
    )


@router.post(
    "/self-service/makeups/{request_id}/deny",
    response_model=MakeupRequestAdminRow,
)
async def deny_makeup_request(
    request_id: str,
    body: DenyMakeupRequestBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> MakeupRequestAdminRow:
    request = await use_cases.deny_makeup_request.execute(
        DenyMakeupRequestCommand(
            request_id=request_id,
            actor_id=claims.user_id,
            reason=body.reason,
        )
    )
    return MakeupRequestAdminRow(
        **request.model_dump(exclude={"academy_id", "parent_id"}),
        student_full_name=None,
    )
