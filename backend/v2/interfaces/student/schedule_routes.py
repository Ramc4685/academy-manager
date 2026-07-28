"""Student's own upcoming schedule (UIM12).

Reuses the exact `GetChildSchedule` use case instance the parent BFF uses
for `GET /parent/children/{student_id}/schedule` — wired in
`composition/student.py`, never imported from `interfaces/parent` (DDD
boundary; import-linter enforced). `GetChildSchedule.execute` still takes a
`parent_id` for its ownership check; we pass the student's own
`ResolvedStudent.parent_id` (the actual parent on the student's roster
record), so the check trivially passes for a student viewing their own
schedule instead of being bypassed.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    StudentNotOwnedByParent,
)
from backend.v2.interfaces.student.deps import (
    ResolvedStudent,
    StudentUseCases,
    get_resolved_student,
    get_student_use_cases,
)
from backend.v2.interfaces.student.views import StudentScheduleEntryView, StudentScheduleResponse

router = APIRouter(tags=["student.schedule"])


@router.get("/schedule", response_model=StudentScheduleResponse)
async def get_my_schedule(
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    resolved: ResolvedStudent = Depends(get_resolved_student),
    use_cases: StudentUseCases = Depends(get_student_use_cases),
) -> StudentScheduleResponse:
    try:
        entries, total = await use_cases.get_child_schedule(  # type: ignore[operator]
            parent_id=resolved.parent_id,
            student_id=resolved.student_id,
            frm=frm,
            to=to,
            limit=limit,
            offset=offset,
        )
    except StudentNotOwnedByParent as err:
        raise HTTPException(status_code=404, detail="Not found") from err

    return StudentScheduleResponse(
        entries=[
            StudentScheduleEntryView(
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
