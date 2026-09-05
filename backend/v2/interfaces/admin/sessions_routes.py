"""Admin sessions + roster routes."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.composition.session_announcements import (
    AnnouncementNotFound,
    SessionAnnouncementService,
    SessionNotFound,
)
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendanceCommand,
)
from backend.v2.contexts.coaching.application.use_cases.mark_coach_attendance import (
    MarkCoachAttendanceCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    AcademyTimezoneUnset,
    CancelEnrollmentCommand,
    CancelSessionCommand,
    CreateSessionCommand,
    DuplicateSessionSeries,
    EditRosterAddCommand,
    EditSessionCommand,
    OverrideEnrollmentFeeCommand,
    PauseEnrollmentCommand,
    TransferEnrollmentCommand,
    WithdrawEnrollmentCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AddSessionReplacementRequest,
    AdminCoachAttendanceView,
    AdminEnrollmentList,
    AdminEnrollmentView,
    AdminSessionList,
    AdminSessionOccurrenceList,
    AdminSessionOccurrenceView,
    AdminSessionView,
    AdminStudentAttendanceView,
    CorrectStudentAttendanceRequest,
    CreateSessionRequest,
    EditRosterAddRequest,
    EditSessionRequest,
    EnrollmentEventDto,
    EnrollmentEventsResponse,
    OverrideEnrollmentFeeRequest,
    PauseEnrollmentRequest,
    RemoveEnrollmentRequest,
    SessionAnnouncementList,
    SessionAnnouncementPostRequest,
    SessionAnnouncementPostResponse,
    SessionAnnouncementView,
    TransferEnrollmentRequest,
    UpdateOccurrenceCoachAttendanceRequest,
    UpdateOccurrenceReplacementRequest,
    UpdateSessionOccurrenceCoachRequest,
    WithdrawEnrollmentRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.tenancy.context import current_academy_id

log = logging.getLogger(__name__)

router = APIRouter(tags=["admin.sessions"])


def _start_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _event_field(event: object, field_name: str, default: object = None) -> object:
    if isinstance(event, dict):
        return event.get(field_name, default)
    return getattr(event, field_name, default)


async def _coach_has_percent_rate(use_cases: AdminUseCases, coach_id: str) -> bool:
    if use_cases.list_coach_pay_rates is None:
        return False
    rates = await use_cases.list_coach_pay_rates.execute(coach_id=coach_id)
    return any(
        getattr(rate, "billing_unit", None) == "percent_of_revenue"
        and getattr(rate, "status", "active") == "active"
        for rate in rates
    )


async def _reject_percent_pay_missing_price(
    *,
    use_cases: AdminUseCases,
    coach_id: str,
    amount_cents: int | None,
) -> None:
    if amount_cents is not None:
        return
    if await _coach_has_percent_rate(use_cases, coach_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Percent-of-revenue coach pay requires a session price. "
                "Set a session fee, use amount_cents: 0 for an explicit free session, "
                "or change the coach pay rate before saving."
            ),
        )


@router.get("/sessions", response_model=AdminSessionList, summary="List sessions for a date range")
async def list_sessions(
    on_date: str = Query(default=None, alias="date"),
    window: str | None = Query(
        default=None,
        description="Set to 'upcoming' to return all sessions starting from today through the next 30 days. Overrides 'date' when both are passed.",
    ),
    coach_id: str | None = Query(default=None, description="Filter sessions by coach ID"),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionList:
    parsed = date.fromisoformat(on_date) if on_date else None
    sessions = await use_cases.list_admin_sessions(parsed, window=window, coach_id=coach_id)  # type: ignore[operator]
    rows = [s if isinstance(s, dict) else s.model_dump(exclude={"academy_id"}) for s in sessions]
    return AdminSessionList(sessions=[AdminSessionView(**s) for s in rows])


@router.post("/sessions", response_model=AdminSessionView, summary="Create a session")
async def create_session(
    body: CreateSessionRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionView:
    await _reject_percent_pay_missing_price(
        use_cases=use_cases,
        coach_id=body.coach_id,
        amount_cents=body.amount_cents,
    )
    try:
        session = await use_cases.create_session.execute(CreateSessionCommand(**body.model_dump()))
    except DuplicateSessionSeries as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AcademyTimezoneUnset as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if use_cases.maintain_session_occurrences is not None:
        await use_cases.maintain_session_occurrences(session)
    return AdminSessionView(**session.model_dump(exclude={"academy_id"}))


@router.patch("/sessions/{session_id}", response_model=AdminSessionView, summary="Edit session")
async def edit_session(
    session_id: str,
    body: EditSessionRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionView:
    field_set = body.model_fields_set
    amount_is_being_cleared = "amount_cents" in field_set and body.amount_cents is None
    if amount_is_being_cleared:
        coach_id = body.coach_id
        if coach_id is None and use_cases.get_admin_session is not None:
            current = await use_cases.get_admin_session(session_id)  # type: ignore[operator]
            if current is not None:
                coach_id = (
                    current.get("coach_id")
                    if isinstance(current, dict)
                    else getattr(current, "coach_id", None)
                )
        if coach_id is not None:
            await _reject_percent_pay_missing_price(
                use_cases=use_cases,
                coach_id=coach_id,
                amount_cents=body.amount_cents,
            )
    try:
        session = await use_cases.edit_session.execute(
            EditSessionCommand(
                session_id=session_id,
                actor_id=claims.user_id,
                **body.model_dump(exclude_unset=True),
            )
        )
    except DuplicateSessionSeries as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AcademyTimezoneUnset as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if use_cases.maintain_session_occurrences is not None:
        await use_cases.maintain_session_occurrences(session)
    return AdminSessionView(**session.model_dump(exclude={"academy_id"}))


@router.get("/sessions/{session_id}", response_model=AdminSessionView, summary="Get session")
async def get_session(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionView:
    if use_cases.get_admin_session is None:
        raise HTTPException(status_code=503, detail="Session detail is not configured")
    row = await use_cases.get_admin_session(session_id)  # type: ignore[operator]
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return AdminSessionView(**row)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Cancel session + emit cascades",
    response_model=None,
)
async def cancel_session(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    session = await use_cases.cancel_session.execute(CancelSessionCommand(session_id=session_id))
    # #467: cancel is a soft delete on `sessions`, but downstream readers (coach
    # day view, payout read models) key off the OCCURRENCE status. Run the same
    # occurrence maintenance create/edit run so future, un-acted-on occurrences
    # follow the parent into "cancelled".
    if session is not None and use_cases.maintain_session_occurrences is not None:
        await use_cases.maintain_session_occurrences(session)  # type: ignore[operator]


@router.get(
    "/sessions/{session_id}/occurrences",
    response_model=AdminSessionOccurrenceList,
    summary="List dated occurrences and coach assignment state for a session",
)
async def list_session_occurrences(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionOccurrenceList:
    rows = await use_cases.list_session_occurrences(session_id)  # type: ignore[operator]
    return AdminSessionOccurrenceList(
        occurrences=[AdminSessionOccurrenceView(**row) for row in rows]
    )


@router.patch(
    "/session-occurrences/{occurrence_id}/coach",
    response_model=AdminSessionOccurrenceView,
    summary="Override actual or substitute coach for a dated occurrence",
)
async def update_session_occurrence_coach(
    occurrence_id: str,
    body: UpdateSessionOccurrenceCoachRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionOccurrenceView:
    row = await use_cases.update_session_occurrence_coach(  # type: ignore[operator]
        occurrence_id=occurrence_id,
        actual_coach_id=body.actual_coach_id,
        substitute_coach_id=body.substitute_coach_id,
        actor_id=claims.user_id,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return AdminSessionOccurrenceView(**row)


@router.patch(
    "/sessions/{session_id}/replacement",
    response_model=AdminSessionOccurrenceView,
    summary="Set replacement coach for a selected recurring session date",
)
async def add_session_replacement(
    session_id: str,
    body: AddSessionReplacementRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionOccurrenceView:
    if use_cases.add_session_replacement is None:
        raise HTTPException(status_code=503, detail="Session replacement is not configured")
    try:
        row = await use_cases.add_session_replacement(  # type: ignore[operator]
            session_id=session_id,
            occurrence_date=body.date,
            replacement_coach_id=body.replacement_coach_id,
            actor_id=claims.user_id,
            reason=body.reason or "replacement coach update",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return AdminSessionOccurrenceView(**row)


@router.patch(
    "/session-occurrences/{occurrence_id}/replacement",
    response_model=AdminSessionOccurrenceView,
    summary="Set replacement coach for one dated occurrence",
)
async def update_session_occurrence_replacement(
    occurrence_id: str,
    body: UpdateOccurrenceReplacementRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminSessionOccurrenceView:
    if use_cases.update_session_occurrence_replacement is None:
        raise HTTPException(status_code=503, detail="Occurrence replacement is not configured")
    try:
        row = await use_cases.update_session_occurrence_replacement(  # type: ignore[operator]
            occurrence_id=occurrence_id,
            replacement_coach_id=body.replacement_coach_id,
            actor_id=claims.user_id,
            reason=body.reason or "replacement coach update",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return AdminSessionOccurrenceView(**row)


@router.patch(
    "/session-occurrences/{occurrence_id}/coach-attendance",
    response_model=AdminCoachAttendanceView,
    summary="Mark coach payroll attendance for a dated occurrence",
)
async def update_occurrence_coach_attendance(
    occurrence_id: str,
    body: UpdateOccurrenceCoachAttendanceRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachAttendanceView:
    try:
        row = await use_cases.mark_coach_attendance.execute(  # type: ignore[attr-defined]
            MarkCoachAttendanceCommand(
                occurrence_id=occurrence_id,
                coach_id=body.coach_id,
                status=body.status,
                role=body.role,
                source="admin",
                rate_override_minor=body.rate_override_minor,
                note=body.note,
            ),
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AdminCoachAttendanceView(**row.model_dump(exclude={"academy_id"}))


@router.patch(
    "/session-occurrences/{occurrence_id}/attendance/{student_id}",
    response_model=AdminStudentAttendanceView,
    summary="Correct a student's recorded attendance for a dated occurrence (#517)",
)
async def correct_occurrence_student_attendance(
    occurrence_id: str,
    student_id: str,
    body: CorrectStudentAttendanceRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentAttendanceView:
    if use_cases.correct_attendance is None:
        raise HTTPException(status_code=503, detail="Attendance correction is not configured")
    result = await use_cases.correct_attendance.execute(  # type: ignore[attr-defined]
        CorrectAttendanceCommand(
            occurrence_id=occurrence_id,
            student_id=student_id,
            status=body.status,
            reason=body.reason,
        ),
        actor_id=claims.user_id,
        actor_role="admin",
    )
    return AdminStudentAttendanceView(**result.model_dump())


@router.get(
    "/sessions/{session_id}/enrollments",
    response_model=AdminEnrollmentList,
    summary="List enrollments for a session",
)
async def list_enrollments(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentList:
    rows = await use_cases.list_admin_enrollments_for_session(session_id)  # type: ignore[operator]
    normalized = [
        {
            **r,
            "full_name": r.get("full_name") or r.get("student_name") or "(unknown)",
        }
        for r in rows
    ]
    return AdminEnrollmentList(enrollments=[AdminEnrollmentView(**r) for r in normalized])


@router.post(
    "/enrollments",
    response_model=AdminEnrollmentView,
    summary="Manually add a student to a session (comp/scholarship path)",
)
async def add_to_roster(
    body: EditRosterAddRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentView:
    try:
        enrollment = await use_cases.edit_roster_add.execute(
            EditRosterAddCommand(**body.model_dump(), actor_id=claims.user_id)
        )
    except DomainError:
        # 404/409 semantics and the machine-readable `error.code` the frontend
        # reads belong to the single global handler; never convert them here.
        raise
    except Exception as exc:
        # #610: an uncaught exception here rendered Starlette's plain-text
        # "Internal Server Error" body, which the API client surfaces verbatim
        # as the banner text — no code, no context, nothing to quote to
        # support. The use case has already released the reserved seat.
        try:
            academy_id: str | None = current_academy_id()
        except Exception:  # pragma: no cover - defensive
            academy_id = None
        log.exception(
            "admin.roster_add_failed",
            extra={
                "academy_id": academy_id,
                "session_id": body.session_id,
                "student_id": body.student_id,
                "actor_id": claims.user_id,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not add this student to the roster. The seat was "
                "released; please retry, and if it keeps failing quote "
                f"session {body.session_id} / student {body.student_id} "
                "to support."
            ),
        ) from exc
    return AdminEnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        student_name=body.full_name,
        full_name=body.full_name,
        parent_id=body.parent_id,
        status=enrollment.status,
        enrolled_at=datetime.now(UTC),
    )


@router.get("/enrollments/{enrollment_id}/events", response_model=EnrollmentEventsResponse)
async def get_enrollment_events(
    enrollment_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> EnrollmentEventsResponse:
    events = await use_cases.list_enrollment_events(enrollment_id)
    return EnrollmentEventsResponse(
        enrollment_id=enrollment_id,
        events=[
            EnrollmentEventDto(
                event_id=str(_event_field(e, "event_id", "")),
                event_type=str(_event_field(e, "event_type", "")),
                effective_date=str(
                    _event_field(e, "effective_date", None) or _event_field(e, "effective_at", "")
                )[:10],
                reason=_event_field(e, "reason"),
                billing_policy=_event_field(e, "billing_policy"),
                billing_result=_event_field(e, "billing_result"),
                credit_id=_event_field(e, "credit_id"),
                refund_id=_event_field(e, "refund_id"),
                metadata=_event_field(e, "metadata", {}) or {},
            )
            for e in events
        ],
    )


@router.delete("/enrollments/{enrollment_id}", status_code=204, response_model=None)
async def cancel_enrollment(
    enrollment_id: str,
    body: RemoveEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.cancel_enrollment.execute(
        CancelEnrollmentCommand(
            enrollment_id=enrollment_id,
            event_type="removed",
            effective_at=_start_of_day_utc(body.effective_date),
            reason=body.reason,
            actor_id=claims.user_id,
        )
    )


@router.post("/enrollments/{enrollment_id}/transfer", response_model=AdminEnrollmentView)
async def transfer_enrollment(
    enrollment_id: str,
    body: TransferEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentView:
    enrollment = await use_cases.transfer_enrollment.execute(
        TransferEnrollmentCommand(
            enrollment_id=enrollment_id,
            target_session_id=body.target_session_id,
            effective_at=_start_of_day_utc(body.effective_date),
            actor_id=claims.user_id,
            reason=body.reason,
        )
    )
    return AdminEnrollmentView(
        enrollment_id=enrollment.enrollment_id,
        session_id=enrollment.session_id,
        student_id=enrollment.student_id,
        student_name="",
        full_name="",
        parent_id="",
        status=enrollment.status,
        enrolled_at=datetime.now(UTC),
    )


@router.post("/enrollments/{enrollment_id}/fee", status_code=204, response_model=None)
async def override_enrollment_fee(
    enrollment_id: str,
    body: OverrideEnrollmentFeeRequest,
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    try:
        await use_cases.override_enrollment_fee.execute(
            OverrideEnrollmentFeeCommand(
                enrollment_id=enrollment_id,
                amount_cents=body.amount_cents,
                actor_id=claims.user_id,
                reason=body.reason,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/enrollments/{enrollment_id}/pause", status_code=204, response_model=None)
async def pause_enrollment(
    enrollment_id: str,
    body: PauseEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.pause_enrollment.execute(
        PauseEnrollmentCommand(
            enrollment_id=enrollment_id,
            effective_at=_start_of_day_utc(body.effective_date),
            actor_id=claims.user_id,
            reason=body.reason,
            resume_on=body.resume_on,
            review_on=body.review_on,
        )
    )


@router.post("/enrollments/{enrollment_id}/withdraw", status_code=204, response_model=None)
async def withdraw_enrollment(
    enrollment_id: str,
    body: WithdrawEnrollmentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.withdraw_enrollment.execute(
        WithdrawEnrollmentCommand(
            enrollment_id=enrollment_id,
            effective_at=_start_of_day_utc(body.effective_date),
            outcome=body.outcome,
            actor_id=claims.user_id,
            reason=body.reason,
        )
    )


@router.post("/enrollments/{enrollment_id}/resume", status_code=204, response_model=None)
async def resume_enrollment(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.resume_enrollment.execute(enrollment_id, actor_id=claims.user_id)


# --- Session announcements (#614) ---------------------------------------
#
# Admin may post to any session in the academy. Wrong persona is a 404 via
# `require_persona("admin")`, per the repo's persona rule.


def _announcement_view(message: object) -> SessionAnnouncementView:
    return SessionAnnouncementView(
        message_id=message.message_id,  # type: ignore[attr-defined]
        session_id=str(message.scope_id or ""),  # type: ignore[attr-defined]
        body=message.body,  # type: ignore[attr-defined]
        urgency=message.urgency,  # type: ignore[attr-defined]
        author_id=message.sender_id,  # type: ignore[attr-defined]
        author_display_name=message.author_display_name,  # type: ignore[attr-defined]
        author_persona=message.sender_persona,  # type: ignore[attr-defined]
        created_at=message.created_at,  # type: ignore[attr-defined]
        # Admin may delete any announcement in the academy.
        can_delete=True,
    )


def _announcements(use_cases: AdminUseCases) -> SessionAnnouncementService:
    service = use_cases.session_announcements
    if service is None:
        raise HTTPException(status_code=503, detail="Announcements are not configured")
    return service


@router.get("/sessions/{session_id}/announcements", response_model=SessionAnnouncementList)
async def list_session_announcements(
    session_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SessionAnnouncementList:
    try:
        messages = await _announcements(use_cases).list_for_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return SessionAnnouncementList(announcements=[_announcement_view(m) for m in messages])


@router.post(
    "/sessions/{session_id}/announcements",
    response_model=SessionAnnouncementPostResponse,
    status_code=201,
)
async def post_session_announcement(
    session_id: str,
    body: SessionAnnouncementPostRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SessionAnnouncementPostResponse:
    try:
        result = await _announcements(use_cases).post(
            session_id=session_id,
            author_id=claims.user_id,
            author_persona="admin",
            body=body.body,
            urgent=body.urgent,
        )
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return SessionAnnouncementPostResponse(
        announcement=_announcement_view(result.message),
        email_status=result.email_status,
        sent_count=result.sent_count,
        failed_count=result.failed_count,
    )


@router.delete(
    "/sessions/{session_id}/announcements/{message_id}",
    status_code=204,
    response_model=None,
)
async def delete_session_announcement(
    session_id: str,
    message_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    try:
        await _announcements(use_cases).delete(
            session_id=session_id,
            message_id=message_id,
            actor_id=claims.user_id,
            actor_is_admin=True,
        )
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail="announcement not found") from exc
