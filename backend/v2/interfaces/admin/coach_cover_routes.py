"""The front desk's "Coach is sick" flow (S66, decisions D-20 and D-21).

* ``GET /admin/coach-cover/options?coach_id=...``: that coach's class dates
  for the next two weeks.
* ``GET /admin/coach-cover/options?occurrence_ids=a,b``: per class date, the
  scheduled coach, the families on the roster, and the coaches free or busy
  then (``composition/coach_cover.py``; "free" means "not teaching then").
* ``GET /admin/session-occurrences/{id}/cancel-preview``: each family's credit
  if the date were cancelled, priced by the cancel use case and written nowhere.
* ``POST /admin/coach-cover/{occurrence_id}/assign``: puts a free coach on the
  date through the existing replacement use case (audit and the S44 coach
  notices included), re-checking at write time that they are free, and posts
  the families' cover notice only when ``notify_families`` is true (D-21).

``require_persona("admin")`` (admins and owners); another academy's ids are 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.v2.composition.coach_cover import (
    Candidate,
    CoachCoverReader,
    CoverNotFound,
    cover_notice,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.sessions_routes import (
    _occurrence_staff_before,
    _schedule_notices,
    _student_names,
)
from backend.v2.interfaces.admin.views import (
    AdminSessionOccurrenceView,
    CreditMissedClassResponse,
    MissedClassFamilyView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.coach-cover"])

_MAX_DATES = 10


def get_coach_cover(request: Request) -> CoachCoverReader:
    reader: CoachCoverReader = request.app.state.coach_cover
    return reader


async def get_cover_candidates(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> list[Candidate]:
    """Active coaches and assistant coaches of this academy."""
    users = await use_cases.list_admin_users.execute(
        roles=("coach", "assistant_coach"), academy_id=claims.academy_id
    )
    return [
        Candidate(coach_id=u.user_id, name=u.display_name or u.email)
        for u in users
        if u.status == "active"
    ]


class CoverCoachView(BaseModel):
    coach_id: str
    name: str


class CoverBusyView(CoverCoachView):
    class_title: str
    start_at: datetime
    end_at: datetime


class CoverFamilyView(BaseModel):
    parent_id: str
    family_name: str
    has_email: bool


class CoverDateView(BaseModel):
    occurrence_id: str
    session_id: str
    title: str
    start_at: datetime
    end_at: datetime
    enrolled_count: int


class CoverOptionsView(BaseModel):
    occurrence_id: str
    session_id: str
    title: str
    start_at: datetime
    end_at: datetime
    status: str
    scheduled_coach: CoverCoachView
    enrolled_count: int
    families: list[CoverFamilyView]
    free: list[CoverCoachView]
    busy: list[CoverBusyView]


class CoverOptionsResponse(BaseModel):
    #: With ``coach_id``: the coach's class dates in the next two weeks.
    dates: list[CoverDateView] = Field(default_factory=list)
    #: With ``occurrence_ids``: who could cover each one.
    options: list[CoverOptionsView] = Field(default_factory=list)


class AssignCoverRequest(BaseModel):
    replacement_coach_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)
    #: D-21: the admin chooses each time; the screen ticks it by default.
    notify_families: bool = False


class AssignCoverResponse(BaseModel):
    occurrence: AdminSessionOccurrenceView
    families_notified: int = 0
    email_failed: int = 0
    announcement_posted: bool = False


@router.get(
    "/coach-cover/options",
    response_model=CoverOptionsResponse,
    summary="A coach's class dates, or who is free to cover given class dates",
)
async def get_cover_options(
    coach_id: str | None = Query(default=None, min_length=1, max_length=128),
    occurrence_ids: str | None = Query(default=None, min_length=1, max_length=1400),
    _claims: AuthClaims = Depends(require_persona("admin")),
    reader: CoachCoverReader = Depends(get_coach_cover),
    candidates: list[Candidate] = Depends(get_cover_candidates),
) -> CoverOptionsResponse:
    if (coach_id is None) == (occurrence_ids is None):
        raise HTTPException(status_code=422, detail="Send coach_id or occurrence_ids")
    if coach_id is not None:
        if not any(c.coach_id == coach_id for c in candidates):
            raise HTTPException(status_code=404, detail="Coach not found")
        dates = await reader.coach_dates(coach_id, now=datetime.now(UTC))
        return CoverOptionsResponse(dates=[CoverDateView(**vars(d)) for d in dates])
    ids = list(dict.fromkeys(i.strip() for i in (occurrence_ids or "").split(",") if i.strip()))
    if not ids or len(ids) > _MAX_DATES:
        raise HTTPException(status_code=422, detail=f"Send 1 to {_MAX_DATES} class dates")
    out: list[CoverOptionsView] = []
    for occurrence_id in ids:
        try:
            o = await reader.options(occurrence_id, candidates)
        except CoverNotFound as exc:
            raise HTTPException(status_code=404, detail="Class date not found") from exc
        occ = o.occurrence
        out.append(
            CoverOptionsView(
                occurrence_id=occ.occurrence_id,
                session_id=occ.template_session_id or occ.session_id,
                title=o.title,
                start_at=occ.start_at,
                end_at=occ.end_at,
                status=occ.status,
                scheduled_coach=CoverCoachView(
                    coach_id=o.scheduled_coach_id, name=o.scheduled_coach_name or "The coach"
                ),
                enrolled_count=o.enrolled_count,
                families=[CoverFamilyView(**vars(f)) for f in o.families],
                free=[CoverCoachView(**vars(c)) for c in o.free],
                busy=[CoverBusyView(**vars(b)) for b in o.busy],
            )
        )
    return CoverOptionsResponse(options=out)


@router.get(
    "/session-occurrences/{occurrence_id}/cancel-preview",
    response_model=CreditMissedClassResponse,
    summary="Each family's credit if this class date were cancelled (writes nothing)",
)
async def get_cancel_preview(
    occurrence_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CreditMissedClassResponse:
    cancel = use_cases.cancel_session_occurrence
    if cancel is None:
        raise HTTPException(status_code=503, detail="Class-date cancellation is not configured")
    preview = await cancel.preview(occurrence_id)
    names = await _student_names(use_cases, [f.student_id for f in preview.families])
    return CreditMissedClassResponse(
        occurrence_id=preview.occurrence.occurrence_id,
        start_at=preview.occurrence.start_at,
        dry_run=True,
        families=[
            MissedClassFamilyView(**f.model_dump(), student_name=names.get(f.student_id or ""))
            for f in preview.families
        ],
        credits_issued=sum(1 for f in preview.families if f.amount_cents > 0),
        credit_total_cents=preview.credit_total_cents,
        credit_skips=dict(preview.credit_skips),
        payroll_flag=preview.payroll_flag,
        schedule_changed=preview.schedule_changed,
    )


@router.post(
    "/coach-cover/{occurrence_id}/assign",
    response_model=AssignCoverResponse,
    summary="Put a free coach on one class date and, if asked, tell the families",
)
async def assign_cover(
    occurrence_id: str,
    body: AssignCoverRequest,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
    reader: CoachCoverReader = Depends(get_coach_cover),
    candidates: list[Candidate] = Depends(get_cover_candidates),
) -> AssignCoverResponse:
    if use_cases.update_session_occurrence_replacement is None:
        raise HTTPException(status_code=503, detail="Occurrence replacement is not configured")
    target = await reader.occurrence(occurrence_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Class date not found")
    if target.status == "cancelled":
        raise HTTPException(status_code=409, detail="This class date is cancelled.")
    if not await reader.is_free(target, body.replacement_coach_id, candidates):
        raise HTTPException(
            status_code=409,
            detail="That coach is teaching then or is this class date's own coach. Review it again.",
        )
    notices = _schedule_notices(request)
    before = await _occurrence_staff_before(notices, occurrence_id)
    try:
        row: dict[str, Any] | None = await use_cases.update_session_occurrence_replacement(  # type: ignore[operator]
            occurrence_id=occurrence_id,
            replacement_coach_id=body.replacement_coach_id,
            actor_id=claims.user_id,
            reason=(body.reason or "").strip() or "Cover: coach unavailable",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Class date not found")
    if notices:
        await notices.occurrence_changed(occurrence_id, before, actor_id=claims.user_id)
    result = AssignCoverResponse(occurrence=AdminSessionOccurrenceView(**row))
    if body.notify_families and use_cases.session_announcements is not None:
        names = {c.coach_id: c.name for c in candidates}
        day, time = await reader.when(target)
        posted = await use_cases.session_announcements.post(
            session_id=target.template_session_id or target.session_id,
            author_id=claims.user_id,
            author_persona="admin",
            body=cover_notice(
                title=await reader.title(target),
                day=day,
                time=time,
                cover=names.get(body.replacement_coach_id, "a cover coach"),
                coach=names.get(target.scheduled_coach_id, "the usual coach"),
            ),
            email=True,
        )
        result.announcement_posted = True
        result.families_notified = posted.sent_count
        result.email_failed = posted.failed_count
    return result
