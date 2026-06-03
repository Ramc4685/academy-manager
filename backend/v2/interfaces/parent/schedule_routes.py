"""Parent child schedule routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    StudentNotOwnedByParent,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import ParentScheduleEntryView, ParentScheduleResponse
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.schedule"])


@router.get(
    "/children/{student_id}/schedule",
    response_model=ParentScheduleResponse,
    summary="Upcoming schedule for a child",
)
async def get_child_schedule(
    student_id: str,
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentScheduleResponse:
    try:
        entries, total = await use_cases.get_child_schedule(  # type: ignore[operator]
            parent_id=claims.user_id,
            student_id=student_id,
            frm=frm,
            to=to,
            limit=limit,
            offset=offset,
        )
    except StudentNotOwnedByParent as err:
        raise HTTPException(status_code=404, detail="Not found") from err

    return ParentScheduleResponse(
        entries=[
            ParentScheduleEntryView(
                occurrence_id=e.occurrence_id,
                session_id=e.session_id,
                session_title=e.session_title,
                location=e.location,
                start_at=e.start_at,
                end_at=e.end_at,
                status=e.status,
                coach_name=e.coach_name,
            )
            for e in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
