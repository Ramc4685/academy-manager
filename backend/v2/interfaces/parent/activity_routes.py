"""Parent children, attendance, and progress read routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentAttendanceRecordView,
    ParentAttendanceResponse,
    ParentChildrenResponse,
    ParentChildView,
    ParentEnrollmentsResponse,
    ParentEnrollmentView,
    ParentProgressNoteView,
    ParentProgressResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.activity"])


@router.get("/children", response_model=ParentChildrenResponse)
async def list_children(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentChildrenResponse:
    rows = await use_cases.list_children_for_parent(claims.user_id)  # type: ignore[operator]
    return ParentChildrenResponse(children=[ParentChildView(**row) for row in rows])


@router.get("/enrollments", response_model=ParentEnrollmentsResponse)
async def list_enrollments(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentEnrollmentsResponse:
    rows = await use_cases.list_enrollments_for_parent(claims.user_id)  # type: ignore[operator]
    return ParentEnrollmentsResponse(enrollments=[ParentEnrollmentView(**row) for row in rows])


@router.get("/attendance", response_model=ParentAttendanceResponse)
async def list_attendance(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAttendanceResponse:
    rows, total = await use_cases.list_attendance_for_parent(  # type: ignore[operator]
        claims.user_id, limit=limit, offset=offset
    )
    return ParentAttendanceResponse(
        records=[ParentAttendanceRecordView(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/progress", response_model=ParentProgressResponse)
async def list_progress(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentProgressResponse:
    rows, total = await use_cases.list_progress_for_parent(  # type: ignore[operator]
        claims.user_id, limit=limit, offset=offset
    )
    return ParentProgressResponse(
        notes=[ParentProgressNoteView(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
