"""Admin / front desk confirm a parent's drop-off report.

Front desk may confirm (``require_staff_tier("front_desk")``: owner, admin,
billing or front desk). Confirming writes a ``present`` mark through
``MarkAttendance`` as a supervisor, so the coach-assignment check is the
only rule skipped; it moves no money.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.composition.dropoff_checkins import DropoffCheckinComposition
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import (
    ConfirmDropoffCommand,
)
from backend.v2.interfaces.admin.staff_tier import require_staff_tier
from backend.v2.interfaces.admin.views import AdminOccurrenceDropoffView
from backend.v2.interfaces.dropoff_views import StaffDropoffCheckinView, dropoff_checkins
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(tags=["admin.dropoff"])


async def admin_dropoff_view(
    dropoff: DropoffCheckinComposition, occurrence_id: str
) -> AdminOccurrenceDropoffView | None:
    summary = await dropoff.reads.occurrence_summary(occurrence_id)
    if summary is None:
        return None
    names = await dropoff.resolve_user_names(
        [
            uid
            for s in summary.checkins
            if s.checkin
            for uid in (s.checkin.reported_by, s.checkin.confirmed_by)
            if uid
        ]
    )
    return AdminOccurrenceDropoffView(
        enabled=summary.enabled,
        expected_student_ids=summary.expected_student_ids,
        expected_count=len(summary.expected_student_ids),
        pending_count=sum(1 for s in summary.checkins if s.state == "pending"),
        confirmed_count=sum(1 for s in summary.checkins if s.state == "confirmed"),
        checkins=[StaffDropoffCheckinView.from_staff_snapshot(s, names) for s in summary.checkins],
    )


@router.post(
    "/session-occurrences/{occurrence_id}/checkins/{student_id}/confirm",
    response_model=StaffDropoffCheckinView,
    summary="Confirm a parent's drop-off report and mark the child present (idempotent)",
)
async def confirm_dropoff(
    occurrence_id: str,
    student_id: str,
    claims: AuthClaims = Depends(require_staff_tier("front_desk")),
    dropoff: DropoffCheckinComposition = Depends(dropoff_checkins),
) -> StaffDropoffCheckinView:
    snapshot = await dropoff.confirm.execute(
        ConfirmDropoffCommand(occurrence_id=occurrence_id, student_id=student_id),
        staff_id=claims.user_id,
        supervisor=True,
    )
    row = snapshot.checkin
    names = await dropoff.resolve_user_names(
        [uid for uid in ((row.reported_by, row.confirmed_by) if row else ()) if uid]
    )
    return StaffDropoffCheckinView.from_staff_snapshot(snapshot, names)
