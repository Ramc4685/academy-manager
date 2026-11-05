"""Coach BFF: the AI-drafted note for tonight's parent email (B4, paid).

* ``POST /coach/students/{student_id}/narrative-draft`` ``{date?}``: drafts
  from the student's wins that day and stores it ``pending_review`` (or
  ``approved`` when the academy turned coach review off). Replaces the day's
  earlier draft. Nothing reaches a parent until a coach approves.
* ``PUT /coach/narratives/{narrative_id}/decision`` ``{status, text?}``:
  approve (with the coach's edits) or reject.
* ``GET /coach/narratives/pending?date=``: the coach's own pending drafts; a
  coach supervisor sees the academy's.

Same guard as the skill routes: the student must be on a session the coach is
assigned to, else 404. ``AiDisabled`` (503), ``AiNotEntitled`` (403),
``AiMonthlyCapReached`` (429) and ``AiProviderError`` (502) pass through.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.skill_routes import _require_assigned_to_student
from backend.v2.interfaces.coach.today_routes import _resolve_date
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach-ai-narratives"])


class NarrativeDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str | None = None


class NarrativeDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    text: str | None = Field(default=None, min_length=1, max_length=500)


def _get_narratives(request: Request) -> object:
    service = getattr(request.app.state, "ai_narratives", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AI narratives are not configured")
    return service


async def _academy_day(
    use_cases: CoachUseCases, academy_id: str, on: date
) -> tuple[datetime, datetime]:
    lookup = getattr(use_cases, "get_academy_timezone", None)
    name = await lookup(academy_id) if lookup is not None else None
    try:
        zone = ZoneInfo(name) if name else UTC
    except (KeyError, ValueError):
        zone = UTC
    start = datetime.combine(on, time.min, tzinfo=zone)
    return start, start + timedelta(days=1)


def _dump(row: Any) -> dict[str, object]:
    return row.model_dump(mode="json")  # type: ignore[no-any-return]


@router.post("/students/{student_id}/narrative-draft", status_code=201)
async def draft_student_narrative(
    student_id: str,
    body: NarrativeDraftBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
    narratives: object = Depends(_get_narratives),
) -> dict[str, object]:
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    on = await _resolve_date(body.date, academy_id=claims.academy_id, use_cases=use_cases)
    start, end = await _academy_day(use_cases, claims.academy_id, on)
    row = await narratives.draft_for_student.execute(  # type: ignore[attr-defined]
        student_id=student_id, for_date=on, start=start, end=end, coach_id=claims.user_id
    )
    return _dump(row)


@router.put("/narratives/{narrative_id}/decision")
async def decide_narrative(
    narrative_id: str,
    body: NarrativeDecisionBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
    narratives: object = Depends(_get_narratives),
) -> dict[str, object]:
    review = narratives.review  # type: ignore[attr-defined]
    row = await review.get(narrative_id)
    if row is None:
        raise HTTPException(status_code=404, detail="narrative not found")
    await _require_assigned_to_student(use_cases, claims.user_id, row.student_id)
    decided = await review.decide(
        narrative_id, status=body.status, text=body.text, approver=claims.user_id
    )
    if decided is None:
        raise HTTPException(status_code=409, detail="narrative is no longer pending review")
    return _dump(decided)


@router.get("/narratives/pending")
async def list_pending_narratives(
    on_date: str | None = Query(None, alias="date"),
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
    narratives: object = Depends(_get_narratives),
) -> dict[str, object]:
    on = await _resolve_date(on_date, academy_id=claims.academy_id, use_cases=use_cases)
    rows = await narratives.review.pending(  # type: ignore[attr-defined]
        on, None if is_coach_supervisor(claims) else claims.user_id
    )
    return {"narratives": [_dump(r) for r in rows]}
