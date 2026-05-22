"""Admin sessions + roster routes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollmentCommand,
    CancelSessionCommand,
    CreateSessionCommand,
    EditRosterAddCommand,
    PauseEnrollmentCommand,
    TransferEnrollmentCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminEnrollmentList,
    AdminEnrollmentView,
    AdminSessionList,
    AdminSessionView,
    CreateSessionRequest,
    EditRosterAddRequest,
    TransferEnrollmentRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.sessions"])


@router.get("/sessions", response_model=AdminSessionList, summary="List sessions for a date range")
async def list_sessions(
    on_date: str = Query(default=None, alias="date"),
    window: str | None = Query(
        default=None,
        description="Set to 'upcoming' to return all sessions starting from today through the next 30 days. Overrides 'date' when both are passed.",
    ),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionList:
    parsed = date.fromisoformat(on_date) if on_date else None
    sessions = await use_cases.list_admin_sessions(parsed, window=window)  # type: ignore[operator]
    rows = [s if isinstance(s, dict) else s.model_dump(exclude={"academy_id"}) for s in sessions]
    return AdminSessionList(sessions=[AdminSessionView(**s) for s in rows])


@router.post("/sessions", response_model=AdminSessionView, summary="Create a session")
async def create_session(
    body: CreateSessionRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionView:
    session = await use_cases.create_session.execute(CreateSessionCommand(**body.model_dump()))
    return AdminSessionView(**session.model_dump(exclude={"academy_id"}))


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Cancel session + emit cascades",
    response_model=None,
)
async def cancel_session(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.cancel_session.execute(CancelSessionCommand(session_id=session_id))


@router.get(
    "/sessions/{session_id}/enrollments",
    response_model=AdminEnrollmentList,
    summary="List enrollments for a session",
)
async def list_enrollments(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentList:
    rows = await use_cases.list_admin_enrollments_for_session(session_id)  # type: ignore[operator]
    normalized = [
        {
            **r,
            "full_name": r.get("full_name") or r.get("student_name") or "(unknown)",
        }
        for r in rows
    ]
    return AdminEnrollmentList(enrollments=[AdminEnrollmentView(**r) for r in normalized])


@router.post(
    "/enrollments",
    response_model=AdminEnrollmentView,
    summary="Manually add a student to a session (comp/scholarship path)",
)
async def add_to_roster(
    body: EditRosterAddRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentView:
    enrollment = await use_cases.edit_roster_add.execute(
        EditRosterAddCommand(**body.model_dump(), actor_id=claims.user_id)
    )
    return AdminEnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        student_name=body.full_name,
        full_name=body.full_name,
        parent_id=body.parent_id,
        status=enrollment.status,
        enrolled_at=datetime.now(UTC),
    )


@router.delete("/enrollments/{enrollment_id}", status_code=204, response_model=None)
async def cancel_enrollment(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.cancel_enrollment.execute(
        CancelEnrollmentCommand(
            enrollment_id=enrollment_id,
            reason="admin_cancel",
            actor_id=claims.user_id,
        )
    )


@router.post("/enrollments/{enrollment_id}/transfer", response_model=AdminEnrollmentView)
async def transfer_enrollment(
    enrollment_id: str,
    body: TransferEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentView:
    enrollment = await use_cases.transfer_enrollment.execute(
        TransferEnrollmentCommand(
            enrollment_id=enrollment_id,
            target_session_id=body.target_session_id,
            actor_id=claims.user_id,
        )
    )
    return AdminEnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        student_name="",
        full_name="",
        parent_id="",
        status=enrollment.status,
        enrolled_at=datetime.now(UTC),
    )


@router.post("/enrollments/{enrollment_id}/pause", status_code=204, response_model=None)
async def pause_enrollment(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.pause_enrollment.execute(
        PauseEnrollmentCommand(enrollment_id=enrollment_id, actor_id=claims.user_id)
    )


@router.post("/enrollments/{enrollment_id}/resume", status_code=204, response_model=None)
async def resume_enrollment(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.resume_enrollment.execute(enrollment_id, actor_id=claims.user_id)
