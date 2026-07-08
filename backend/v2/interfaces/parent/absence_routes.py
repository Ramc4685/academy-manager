"""Parent absence-notice routes (R1)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    SubmitAbsenceNoticeCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.absence_notices"])


class CreateAbsenceNoticeRequest(BaseModel):
    student_id: str
    occurrence_id: str


class AbsenceNoticeView(BaseModel):
    notice_id: str
    student_id: str
    occurrence_id: str
    session_id: str
    submitted_by: str
    submitted_at: datetime
    notice_window_met: bool


class AbsenceNoticesResponse(BaseModel):
    notices: list[AbsenceNoticeView]


@router.post(
    "/absences",
    response_model=AbsenceNoticeView,
    status_code=status.HTTP_201_CREATED,
)
async def create_absence_notice(
    body: CreateAbsenceNoticeRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> AbsenceNoticeView:
    notice = await use_cases.submit_absence_notice.execute(
        SubmitAbsenceNoticeCommand(
            parent_id=claims.user_id,
            student_id=body.student_id,
            occurrence_id=body.occurrence_id,
        )
    )
    return AbsenceNoticeView(**notice.model_dump(exclude={"academy_id"}))


@router.get("/absences", response_model=AbsenceNoticesResponse)
async def list_absences(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> AbsenceNoticesResponse:
    rows = await use_cases.list_parent_absences.execute(claims.user_id)
    return AbsenceNoticesResponse(
        notices=[AbsenceNoticeView(**r.model_dump(exclude={"academy_id"})) for r in rows]
    )
