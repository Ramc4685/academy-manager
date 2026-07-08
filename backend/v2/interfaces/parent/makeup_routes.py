"""Parent makeup-request routes (R2)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    SubmitMakeupRequestCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.makeup_requests"])


class CreateMakeupRequestRequest(BaseModel):
    student_id: str
    missed_occurrence_id: str
    requested_target_occurrence_id: str | None = None


class MakeupRequestView(BaseModel):
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


class MakeupRequestsResponse(BaseModel):
    makeups: list[MakeupRequestView]


class MakeupTargetView(BaseModel):
    occurrence_id: str
    session_id: str
    title: str
    start_at: datetime
    end_at: datetime
    open_slots: int


class MakeupTargetsResponse(BaseModel):
    targets: list[MakeupTargetView]


@router.post(
    "/makeups",
    response_model=MakeupRequestView,
    status_code=status.HTTP_201_CREATED,
)
async def create_makeup_request(
    body: CreateMakeupRequestRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> MakeupRequestView:
    request = await use_cases.submit_makeup_request.execute(
        SubmitMakeupRequestCommand(
            parent_id=claims.user_id,
            student_id=body.student_id,
            missed_occurrence_id=body.missed_occurrence_id,
            requested_target_occurrence_id=body.requested_target_occurrence_id,
        )
    )
    return MakeupRequestView(**request.model_dump(exclude={"academy_id", "parent_id"}))


@router.get("/makeups", response_model=MakeupRequestsResponse)
async def list_makeups(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> MakeupRequestsResponse:
    rows = await use_cases.list_parent_makeups.execute(claims.user_id)
    return MakeupRequestsResponse(
        makeups=[
            MakeupRequestView(**r.model_dump(exclude={"academy_id", "parent_id"})) for r in rows
        ]
    )


@router.get("/makeups/eligible-targets", response_model=MakeupTargetsResponse)
async def list_eligible_makeup_targets(
    student_id: str = Query(...),
    missed_occurrence_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> MakeupTargetsResponse:
    targets = await use_cases.list_eligible_makeup_targets.execute(
        parent_id=claims.user_id,
        student_id=student_id,
        missed_occurrence_id=missed_occurrence_id,
    )
    return MakeupTargetsResponse(targets=[MakeupTargetView(**t.model_dump()) for t in targets])
