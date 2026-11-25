"""Coach confirms a parent's drop-off report, which writes the attendance mark.

Assigned coaches (scheduled, actual, substitute, assistant) only; admin and
owner confirm any class as supervisors, exactly like ``POST /coach/attendance``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.composition.dropoff_checkins import DropoffCheckinComposition
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    ConfirmDropoffCommand,
)
from backend.v2.interfaces.dropoff_views import StaffDropoffCheckinView, dropoff_checkins
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach"])


@router.post(
    "/occurrences/{occurrence_id}/checkins/{student_id}/confirm",
    response_model=StaffDropoffCheckinView,
    summary="Confirm a parent's drop-off report and mark the child present (idempotent)",
)
async def confirm_dropoff(
    occurrence_id: str,
    student_id: str,
    claims: AuthClaims = Depends(require_coach_surface()),
    dropoff: DropoffCheckinComposition = Depends(dropoff_checkins),
) -> StaffDropoffCheckinView:
    snapshot = await dropoff.confirm.execute(
        ConfirmDropoffCommand(occurrence_id=occurrence_id, student_id=student_id),
        staff_id=claims.user_id,
        supervisor=is_coach_supervisor(claims),
    )
    return StaffDropoffCheckinView.from_staff_snapshot(snapshot)
