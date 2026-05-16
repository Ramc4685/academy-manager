"""Admin sessions + roster routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollmentCommand,
    CancelSessionCommand,
    CreateSessionCommand,
    EditRosterAddCommand,
    PauseEnrollmentCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminEnrollmentList,
    AdminEnrollmentView,
    AdminSessionList,
    AdminSessionView,
    CreateSessionRequest,
    EditRosterAddRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.sessions"])


@router.get("/sessions", response_model=AdminSessionList, summary="List sessions for a date range")
async def list_sessions(
    on_date: str = Query(default=None, alias="date"),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionList:
    parsed = date.fromisoformat(on_date) if on_date else None
    sessions = await use_cases.list_admin_sessions(parsed)  # type: ignore[operator]
    return AdminSessionList(
        sessions=[AdminSessionView(**s.model_dump(exclude={"academy_id"})) for s in sessions]
    )


@router.post("/sessions", response_model=AdminSessionView, summary="Create a session")
async def create_session(
    body: CreateSessionRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionView:
    session = await use_cases.create_session.execute(
        CreateSessionCommand(**body.model_dump())
    )
    return AdminSessionView(**session.model_dump(exclude={"academy_id"}))


@router.delete("/sessions/{session_id}", status_code=204, summary="Cancel session + emit cascades")
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
    return AdminEnrollmentList(enrollments=[AdminEnrollmentView(**r) for r in rows])


@router.post(
    "/enrollments",
    response_model=AdminEnrollmentView,
    summary="Manually add a student to a session (comp/scholarship path)",
)
async def add_to_roster(
    body: EditRosterAddRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentView:
    enrollment = await use_cases.edit_roster_add.execute(
        EditRosterAddCommand(**body.model_dump())
    )
    return AdminEnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        student_name=body.full_name,
        parent_id=body.parent_id,
        status=enrollment.status,
    )


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def cancel_enrollment(
    enrollment_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.cancel_enrollment.execute(
        CancelEnrollmentCommand(enrollment_id=enrollment_id, reason="admin_cancel")
    )


@router.post("/enrollments/{enrollment_id}/pause", status_code=204)
async def pause_enrollment(
    enrollment_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.pause_enrollment.execute(
        PauseEnrollmentCommand(enrollment_id=enrollment_id)
    )


@router.post("/enrollments/{enrollment_id}/resume", status_code=204)
async def resume_enrollment(
    enrollment_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.resume_enrollment.execute(enrollment_id)
