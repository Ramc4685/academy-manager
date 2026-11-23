"""Parent drop-off check-in: "I've arrived" for one child on one class date.

The report is never attendance; staff confirm it, and that confirmation
writes the mark. Every rule (switch, ownership, academy, enrollment,
occurrence status, window) is checked on the server.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.composition.dropoff_checkins import DropoffCheckinComposition
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    ReportArrivalCommand,
)
from backend.v2.interfaces.dropoff_views import DropoffCheckinView, dropoff_checkins
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.dropoff"])


@router.post(
    "/children/{student_id}/occurrences/{occurrence_id}/arrival",
    response_model=DropoffCheckinView,
    summary="Report that a child has arrived for a class date (idempotent)",
)
async def report_arrival(
    student_id: str,
    occurrence_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    dropoff: DropoffCheckinComposition = Depends(dropoff_checkins),
) -> DropoffCheckinView:
    snapshot = await dropoff.report.execute(
        ReportArrivalCommand(
            parent_id=claims.user_id, student_id=student_id, occurrence_id=occurrence_id
        )
    )
    return DropoffCheckinView.from_snapshot(snapshot)
