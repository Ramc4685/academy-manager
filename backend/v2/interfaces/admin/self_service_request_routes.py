"""Admin routes for reviewing parent self-service requests (R2).

Covers the admin absence-notice queue plus makeup-request review
(list/approve/deny). Approval has NO billing dependency — the student
already paid for the missed session; see the use case docstring in
``makeup_requests.py`` for the BILLING SAFETY constraint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ApproveMakeupRequestCommand,
    DenyMakeupRequestCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    ApproveTrialRequestCommand,
    DenyTrialRequestCommand,
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


class TrialRequestAdminRow(BaseModel):
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


class TrialRequestsAdminResponse(BaseModel):
    trials: list[TrialRequestAdminRow]


class ApproveTrialRequestBody(BaseModel):
    occurrence_id: str


class DenyTrialRequestBody(BaseModel):
    reason: str


class SelfCancellationAdminRow(BaseModel):
    enrollment_id: str
    student_id: str
    session_id: str
    cancellation_reason: str | None
    cancellation_policy_snapshot: dict[str, Any] | None
    cancelled_at: datetime | None
    student_full_name: str | None
    session_title: str | None


class SelfCancellationsAdminResponse(BaseModel):
    cancellations: list[SelfCancellationAdminRow]


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


@router.get("/self-service/trials", response_model=TrialRequestsAdminResponse)
async def list_trials_for_admin(
    status: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> TrialRequestsAdminResponse:
    rows = await use_cases.list_trial_requests_for_admin.execute(status)
    return TrialRequestsAdminResponse(
        trials=[
            TrialRequestAdminRow(**row.model_dump(exclude={"academy_id", "parent_user_id"}))
            for row in rows
        ]
    )


@router.post(
    "/self-service/trials/{request_id}/approve",
    response_model=TrialRequestAdminRow,
)
async def approve_trial_request(
    request_id: str,
    body: ApproveTrialRequestBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> TrialRequestAdminRow:
    request = await use_cases.approve_trial_request.execute(
        ApproveTrialRequestCommand(
            request_id=request_id,
            actor_id=claims.user_id,
            occurrence_id=body.occurrence_id,
        )
    )
    return TrialRequestAdminRow(**request.model_dump(exclude={"academy_id", "parent_user_id"}))


@router.post(
    "/self-service/trials/{request_id}/deny",
    response_model=TrialRequestAdminRow,
)
async def deny_trial_request(
    request_id: str,
    body: DenyTrialRequestBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> TrialRequestAdminRow:
    request = await use_cases.deny_trial_request.execute(
        DenyTrialRequestCommand(
            request_id=request_id,
            actor_id=claims.user_id,
            reason=body.reason,
        )
    )
    return TrialRequestAdminRow(**request.model_dump(exclude={"academy_id", "parent_user_id"}))


@router.get("/self-service/cancellations", response_model=SelfCancellationsAdminResponse)
async def list_self_cancellations_for_admin(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfCancellationsAdminResponse:
    rows = await use_cases.list_self_cancellations_for_admin.execute()
    return SelfCancellationsAdminResponse(
        cancellations=[SelfCancellationAdminRow(**row.model_dump()) for row in rows]
    )
