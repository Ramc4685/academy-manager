"""Coach roster routes.

GET    /coach/sessions/{session_id}/roster              — view roster (assigned only)
POST   /coach/sessions/{session_id}/roster              — disabled for launch
DELETE /coach/sessions/{session_id}/roster/{student_id} — disabled for launch

Unassigned coach → 403 (checked before delegating to use cases).
Wrong persona    → 404 (require_persona guard).
Unauthenticated  → 401.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    AddStudentToRosterRequest,
    AddStudentToRosterResponse,
    RosterEntryView,
    RosterResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach.roster"])

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="session not assigned to coach"
)
_ROSTER_MUTATION_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="coach roster changes are disabled; admin approval is required",
)


async def _require_assigned(use_cases: CoachUseCases, coach_id: str, session_id: str) -> None:
    if not await use_cases.assigned_sessions.is_coach_assigned(coach_id, session_id):
        raise _FORBIDDEN


@router.get(
    "/sessions/{session_id}/roster",
    response_model=RosterResponse,
    summary="Get roster for an assigned session",
)
async def get_roster(
    session_id: str,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> RosterResponse:
    await _require_assigned(use_cases, claims.user_id, session_id)
    entries = await use_cases.get_roster.execute(session_id)
    return RosterResponse(
        roster=[
            RosterEntryView(
                enrollment_id=e.enrollment_id,
                student_id=e.student_id,
                full_name=e.full_name,
                enrollment_status=e.status,
            )
            for e in entries
        ]
    )


@router.post(
    "/sessions/{session_id}/roster",
    response_model=AddStudentToRosterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a student to an assigned session roster",
)
async def add_student_to_roster(
    session_id: str,
    body: AddStudentToRosterRequest,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> AddStudentToRosterResponse:
    _ = session_id, body, claims, use_cases
    raise _ROSTER_MUTATION_FORBIDDEN


@router.delete(
    "/sessions/{session_id}/roster/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a student from an assigned session roster",
)
async def remove_student_from_roster(
    session_id: str,
    student_id: str,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> None:
    _ = session_id, student_id, claims, use_cases
    raise _ROSTER_MUTATION_FORBIDDEN
