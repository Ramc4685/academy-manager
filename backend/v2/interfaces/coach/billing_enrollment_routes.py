"""Coach billing-enrollment routes.

GET  /coach/billing-enrollments                         — list active StudentBillingEnrollment
                                                          records for the coach's students
GET  /coach/billing-enrollments/{enrollment_id}/move/preview
                                                        — proration preview (no side effects)
POST /coach/billing-enrollments/{enrollment_id}/move    — apply session-type move

All routes require the `coach` persona.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    MoveStudentSessionTypeCommand,
    PreviewStudentSessionTypeMoveCommand,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachBillingEnrollmentView,
    MoveEnrollmentResponse,
    ProrationPreviewView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach.billing"])


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------


class MoveEnrollmentRequest(BaseModel):
    to_session_type_id: str
    move_date: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_period(move_date: datetime) -> tuple[datetime, datetime]:
    """Return a sensible (period_start, period_end) for the calendar month of move_date."""
    start = move_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # First day of next month
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _ensure_utc(dt: datetime) -> datetime:
    """Attach UTC timezone to a naive datetime; leave timezone-aware datetimes unchanged."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _verify_coach_owns_enrollment(
    enrollment,
    coach_id: str,
    assigned_sessions,
    get_active_session_enrollments_for_student,
) -> None:
    """Raise 403 if the coach is not assigned to any session the student is enrolled in."""
    session_enrollments = await get_active_session_enrollments_for_student(enrollment.student_id)
    for se in session_enrollments:
        if await assigned_sessions.is_coach_assigned(coach_id, se.session_id):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="enrollment not accessible to this coach",
    )


# ---------------------------------------------------------------------------
# GET /coach/billing-enrollments
# ---------------------------------------------------------------------------


@router.get(
    "/billing-enrollments",
    response_model=list[CoachBillingEnrollmentView],
    summary="List billing enrollments for students in the coach's sessions",
)
async def list_billing_enrollments(
    session_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> list[CoachBillingEnrollmentView]:
    # Verify coach is assigned to the session before returning data.
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="session not assigned to coach",
        )
    roster = await use_cases.get_roster.execute(session_id)
    student_ids = {e.student_id for e in roster}

    if not student_ids:
        return []

    # Fetch billing enrollments per student and flatten.
    all_enrollments = []
    for sid in student_ids:
        enrollments = await use_cases.list_billing_enrollments.execute(student_id=sid)
        all_enrollments.extend(enrollments)

    session_types = await use_cases.list_session_types.execute()
    st_map = {st.session_type_id: st for st in session_types}

    return [
        CoachBillingEnrollmentView(
            enrollment_id=e.enrollment_id,
            student_id=e.student_id,
            session_type_id=e.session_type_id,
            session_type_name=st_map.get(e.session_type_id, None).name  # type: ignore[union-attr]
            if e.session_type_id in st_map
            else "(unknown)",
            status=e.status,
            billing_start_date=e.billing_start_date,
            override_price_cents=e.override_price_cents,
        )
        for e in all_enrollments
    ]


# ---------------------------------------------------------------------------
# GET /coach/billing-enrollments/{enrollment_id}/move/preview
# ---------------------------------------------------------------------------


@router.get(
    "/billing-enrollments/{enrollment_id}/move/preview",
    response_model=ProrationPreviewView,
    summary="Preview proration for a session-type move (no side effects)",
)
async def move_preview(
    enrollment_id: str,
    to_session_type_id: str = Query(...),
    move_date: datetime | None = Query(default=None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> ProrationPreviewView:
    enrollment = await use_cases.get_billing_enrollment(enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="enrollment not found")

    await _verify_coach_owns_enrollment(
        enrollment,
        claims.user_id,
        use_cases.assigned_sessions,
        use_cases.get_active_session_enrollments_for_student,
    )

    effective_move_date = _ensure_utc(move_date or datetime.now(UTC))
    period_start, period_end = _default_period(effective_move_date)
    proration = await use_cases.preview_student_session_type_move.execute(
        PreviewStudentSessionTypeMoveCommand(
            enrollment_id=enrollment_id,
            to_session_type_id=to_session_type_id,
            move_date=effective_move_date,
            period_start=period_start,
            period_end=period_end,
        )
    )

    return ProrationPreviewView(
        credit_cents=proration.credit_cents,
        charge_cents=proration.charge_cents,
        net_cents=proration.net_cents,
        from_session_type_id=proration.from_session_type_id,
        to_session_type_id=proration.to_session_type_id,
    )


# ---------------------------------------------------------------------------
# POST /coach/billing-enrollments/{enrollment_id}/move
# ---------------------------------------------------------------------------


@router.post(
    "/billing-enrollments/{enrollment_id}/move",
    response_model=MoveEnrollmentResponse,
    summary="Apply a session-type move for a student billing enrollment",
)
async def move_enrollment(
    enrollment_id: str,
    body: MoveEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> MoveEnrollmentResponse:
    enrollment = await use_cases.get_billing_enrollment(enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="enrollment not found")

    await _verify_coach_owns_enrollment(
        enrollment,
        claims.user_id,
        use_cases.assigned_sessions,
        use_cases.get_active_session_enrollments_for_student,
    )

    effective_move_date = _ensure_utc(body.move_date or datetime.now(UTC))

    if body.period_start is not None and body.period_end is not None:
        period_start = _ensure_utc(body.period_start)
        period_end = _ensure_utc(body.period_end)
    else:
        period_start, period_end = _default_period(effective_move_date)

    cmd = MoveStudentSessionTypeCommand(
        enrollment_id=enrollment_id,
        to_session_type_id=body.to_session_type_id,
        move_date=effective_move_date,
        period_start=period_start,
        period_end=period_end,
        actor_id=claims.user_id,
        reason=body.reason,
    )

    result = await use_cases.move_student_session_type.execute(cmd)

    # Build session type name map for the response view
    session_types = await use_cases.list_session_types.execute()
    st_map = {st.session_type_id: st for st in session_types}

    updated = result.enrollment
    st = st_map.get(updated.session_type_id)

    return MoveEnrollmentResponse(
        enrollment=CoachBillingEnrollmentView(
            enrollment_id=updated.enrollment_id,
            student_id=updated.student_id,
            session_type_id=updated.session_type_id,
            session_type_name=st.name if st else "(unknown)",
            status=updated.status,
            billing_start_date=updated.billing_start_date,
            override_price_cents=updated.override_price_cents,
        ),
        proration=ProrationPreviewView(
            credit_cents=result.proration.credit_cents,
            charge_cents=result.proration.charge_cents,
            net_cents=result.proration.net_cents,
            from_session_type_id=result.proration.from_session_type_id,
            to_session_type_id=result.proration.to_session_type_id,
        ),
    )
