"""POST /api/v2/coach/attendance — mark attendance.

Idempotent on mutation_id. Returns 200 (not 201) so idempotent replays
look the same as first writes from the client's POV.

Conflict cases per docs/offline-policy.md surface as 409 with structured
error codes (Coaching.SessionCancelled / SessionNotAssigned /
StudentNotEnrolled / ConflictAttendanceExists).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkAttendanceEntry,
    BulkMarkAttendanceCommand,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendanceCommand,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    BulkAttendanceEntryResponse,
    BulkMarkAttendanceRequest,
    BulkMarkAttendanceResponse,
    MarkAttendanceRequest,
    MarkAttendanceResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach"])


@router.post(
    "/attendance",
    response_model=MarkAttendanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark attendance for one student in a session (idempotent on mutation_id)",
)
async def mark_attendance(
    body: MarkAttendanceRequest,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> MarkAttendanceResponse:
    cmd = MarkAttendanceCommand(
        mutation_id=body.mutation_id,
        occurrence_id=body.occurrence_id,
        session_id=body.session_id,
        student_id=body.student_id,
        status=body.status,
        marked_at_client=body.marked_at_client,
        client_app_version=body.client_app_version,
    )
    result = await use_cases.mark_attendance.execute(cmd, coach_id=claims.user_id)
    return MarkAttendanceResponse(
        attendance_id=result.attendance_id,
        occurrence_id=result.occurrence_id,
        session_id=result.session_id,
        student_id=result.student_id,
        status=result.status,
        marked_at=result.marked_at,
    )


@router.post(
    "/occurrences/{occurrence_id}/attendance/bulk",
    response_model=BulkMarkAttendanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk mark attendance for all students in one occurrence (idempotent on mutation_id)",
)
async def bulk_mark_attendance(
    occurrence_id: str,
    body: BulkMarkAttendanceRequest,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> BulkMarkAttendanceResponse:
    cmd = BulkMarkAttendanceCommand(
        mutation_id=body.mutation_id,
        occurrence_id=occurrence_id,
        session_id=body.session_id,
        entries=[
            BulkAttendanceEntry(student_id=e.student_id, status=e.status) for e in body.entries
        ],
    )
    result = await use_cases.bulk_mark_attendance.execute(cmd, coach_id=claims.user_id)
    return BulkMarkAttendanceResponse(
        results=[
            BulkAttendanceEntryResponse(
                student_id=r.student_id,
                status=r.status,
                attendance_id=r.attendance_id,
            )
            for r in result.results
        ]
    )
