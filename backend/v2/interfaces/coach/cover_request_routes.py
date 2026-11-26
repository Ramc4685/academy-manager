"""POST/GET /api/v2/coach/cover-requests (S67, docs/design/coach-sick.md 8.4).

A coach tells the academy they can't make a class date. It writes one
academy-inbox message and nothing else: no cancellation, no cover, no family
message, no email. Only the front desk's "Coach is sick" flow acts on it.

The caller must be assigned to the date (lead, cover or assistant); anyone
else gets 404. Services: ``app.state.coach_cover`` (``composition/coach_cover.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.composition.coach_cover import CoachCoverReader, user_facts
from backend.v2.composition.coach_roster_health import is_assigned
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_surface

router = APIRouter(tags=["coach.cover-requests"])


class CoverRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=200)


class CoverRequestView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_at: datetime | None = None


def _view(at: datetime | None) -> CoverRequestView:
    """Stored datetimes come back naive from Mongo; they are UTC."""
    return CoverRequestView(requested_at=at.replace(tzinfo=at.tzinfo or UTC) if at else None)


def get_coach_cover(request: Request) -> CoachCoverReader:
    reader: CoachCoverReader = request.app.state.coach_cover
    return reader


async def _assigned(
    reader: CoachCoverReader, occurrence_id: str, user_id: str
) -> SessionOccurrence:
    occurrence = await reader.occurrence(occurrence_id)
    if occurrence is None or not is_assigned(occurrence, user_id):
        raise HTTPException(status_code=404, detail="Not found")
    return occurrence


def cover_request_body(*, coach: str, title: str, day: str, time: str, reason: str | None) -> str:
    """The coach's message to the academy inbox (coach-sick.md section 6)."""
    body = f"{coach} can't make {title} on {day} at {time}."
    reason = (reason or "").strip()
    return f"{body} Reason: {reason.rstrip('.')}." if reason else body


@router.post(
    "/cover-requests",
    response_model=CoverRequestView,
    summary="Tell the academy I can't make a class date (inbox message only)",
)
async def request_cover(
    body: CoverRequestBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    reader: CoachCoverReader = Depends(get_coach_cover),
) -> CoverRequestView:
    occurrence = await _assigned(reader, body.occurrence_id, claims.user_id)
    existing = await reader.cover_request(occurrence.occurrence_id, claims.user_id)
    if existing is not None:
        return _view(existing.created_at)
    start = (
        occurrence.start_at
        if occurrence.start_at.tzinfo
        else occurrence.start_at.replace(tzinfo=UTC)
    )
    if occurrence.status == "cancelled" or start <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="This class date has started or is cancelled.")
    day, time = await reader.when(occurrence)
    facts = await user_facts(reader.db, [claims.user_id])
    coach = (facts.get(claims.user_id) or {}).get("name") or "A coach"
    message, _ = await reader.request_cover(
        occurrence,
        coach_id=claims.user_id,
        body=cover_request_body(
            coach=coach,
            title=await reader.title(occurrence) or "a class",
            day=day,
            time=time,
            reason=body.reason,
        ),
    )
    return _view(message.created_at)


@router.get(
    "/cover-requests",
    response_model=CoverRequestView,
    summary="When I asked for cover on a class date, if I did",
)
async def get_cover_request(
    occurrence_id: str = Query(min_length=1, max_length=128),
    claims: AuthClaims = Depends(require_coach_surface()),
    reader: CoachCoverReader = Depends(get_coach_cover),
) -> CoverRequestView:
    occurrence = await _assigned(reader, occurrence_id, claims.user_id)
    existing = await reader.cover_request(occurrence.occurrence_id, claims.user_id)
    return _view(existing.created_at if existing else None)
