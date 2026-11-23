"""Parent child schedule routes."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.composition.dropoff_checkins import DropoffCheckinComposition
from backend.v2.contexts.coaching.application.use_cases.dropoff_checkin import OccurrenceRef
from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    StudentNotOwnedByParent,
)
from backend.v2.interfaces.dropoff_views import DropoffCheckinView, optional_dropoff_checkins
from backend.v2.interfaces.parent.absence_makeup import describe_absence_makeups
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
    dropoff: DropoffCheckinComposition | None = Depends(optional_dropoff_checkins),
) -> ParentScheduleResponse:
    # With drop-off on, a class that started stays listed through its
    # check-in window and an hour after, so "I've arrived", "Checked in" and
    # "not confirmed" stay reachable after the start time.
    policy = await dropoff.reads.policy() if dropoff is not None else None
    started_within = (
        timedelta(minutes=policy.closes_minutes_after + 60)
        if policy is not None and policy.enabled
        else timedelta(0)
    )
    try:
        entries, total = await use_cases.get_child_schedule(  # type: ignore[operator]
            parent_id=claims.user_id,
            student_id=student_id,
            frm=frm,
            to=to,
            limit=limit,
            offset=offset,
            include_started_within=started_within,
        )
    except StudentNotOwnedByParent as err:
        raise HTTPException(status_code=404, detail="Not found") from err

    checkins = (
        await dropoff.reads.for_student(
            student_id,
            [
                OccurrenceRef(occurrence_id=e.occurrence_id, starts_at=e.start_at, status=e.status)
                for e in entries
            ],
        )
        if dropoff is not None and entries
        else None
    ) or {}

    # Only dates this (ownership-checked) child already reported.
    makeups = await describe_absence_makeups(
        use_cases, [(student_id, e.occurrence_id) for e in entries if e.absence_reported]
    )
    return ParentScheduleResponse(
        entries=[
            ParentScheduleEntryView(
                checkin=(
                    DropoffCheckinView.from_snapshot(checkins[e.occurrence_id])
                    if e.occurrence_id in checkins
                    else None
                ),
                can_report_arrival=(
                    e.occurrence_id in checkins and checkins[e.occurrence_id].can_report_arrival
                ),
                occurrence_id=e.occurrence_id,
                session_id=e.session_id,
                session_title=e.session_title,
                location=e.location,
                start_at=e.start_at,
                end_at=e.end_at,
                status=e.status,
                coach_name=e.coach_name,
                source=e.source,
                cancellation_reason=e.cancellation_reason,
                absence_reported=e.absence_reported,
                absence_makeup=makeups.get((student_id, e.occurrence_id)),
            )
            for e in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
