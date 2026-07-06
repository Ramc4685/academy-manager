"""Parent trial-request routes (R3).

Parents submit a request to try a session before enrolling — either for an
existing student or a prospective child not yet in the system. Admin
review (see ``interfaces/admin/self_service_request_routes.py``) approves
or denies. Approval never involves billing: trial fee handling is out of
v1 scope (no-charge trials only).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    SubmitTrialRequestCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.trial_requests"])


class CreateTrialRequestRequest(BaseModel):
    student_ref: str
    requested_session_id: str
    preferred_start: str
    preferred_end: str
    student_id: str | None = None
    prospective_child_name: str | None = None
    prospective_child_dob: str | None = None


class TrialRequestView(BaseModel):
    request_id: str
    student_ref: str
    student_id: str | None
    prospective_child_name: str | None
    prospective_child_dob: str | None
    requested_session_id: str
    preferred_start: str
    preferred_end: str
    status: str
    assigned_occurrence_id: str | None
    linked_application_id: str | None
    denial_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


class TrialRequestsResponse(BaseModel):
    trials: list[TrialRequestView]


@router.post(
    "/trial-requests",
    response_model=TrialRequestView,
    status_code=status.HTTP_201_CREATED,
)
async def create_trial_request(
    body: CreateTrialRequestRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> TrialRequestView:
    request = await use_cases.submit_trial_request.execute(
        SubmitTrialRequestCommand(
            parent_user_id=claims.user_id,
            student_ref=body.student_ref,
            student_id=body.student_id,
            prospective_child_name=body.prospective_child_name,
            prospective_child_dob=body.prospective_child_dob,
            requested_session_id=body.requested_session_id,
            preferred_start=body.preferred_start,
            preferred_end=body.preferred_end,
        )
    )
    return TrialRequestView(**request.model_dump(exclude={"academy_id", "parent_user_id"}))


@router.get("/trial-requests", response_model=TrialRequestsResponse)
async def list_trial_requests(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> TrialRequestsResponse:
    rows = await use_cases.list_parent_trial_requests.execute(claims.user_id)
    return TrialRequestsResponse(
        trials=[
            TrialRequestView(**r.model_dump(exclude={"academy_id", "parent_user_id"})) for r in rows
        ]
    )
