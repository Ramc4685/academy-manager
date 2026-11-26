"""GET /api/v2/coach/roster-health?occurrence_id=... (S49, decision D-14).

A child's medical note, emergency contact and parent phone for one class
date, for the coaches assigned to it (lead, cover, assistant) and coach
supervisors. Anyone else gets 404, including by URL: an unassigned coach, an
assistant on another class, a parent, another academy.

Its own path on purpose: the service worker caches ``/coach/(today|sessions)``
for 24h and the query persister stores coach reads in localStorage, so this
data must never ride on those payloads. ``Cache-Control: no-store`` keeps any
HTTP cache from holding it either. Services: ``app.state.coach_roster_health``
(``composition/coach_roster_health.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.v2.composition.coach_roster_health import (
    HealthStatus,
    RosterHealthReader,
    is_assigned,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach.roster-health"])

NO_STORE = "no-store"


class CoachChildHealthView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str
    full_name: str
    status: HealthStatus
    note: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None


class CoachRosterHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: str
    declared_count: int
    children: list[CoachChildHealthView]


def get_roster_health_reader(request: Request) -> RosterHealthReader:
    reader: RosterHealthReader = request.app.state.coach_roster_health
    return reader


@router.get(
    "/roster-health",
    response_model=CoachRosterHealthResponse,
    summary="Health notes and emergency contacts for an assigned class date (never cached)",
)
async def get_roster_health(
    response: Response,
    occurrence_id: str = Query(min_length=1, max_length=128),
    claims: AuthClaims = Depends(require_coach_surface()),
    reader: RosterHealthReader = Depends(get_roster_health_reader),
) -> CoachRosterHealthResponse:
    response.headers["Cache-Control"] = NO_STORE
    occurrence = await reader.occurrence(occurrence_id)
    if occurrence is None or not (
        is_coach_supervisor(claims) or is_assigned(occurrence, claims.user_id)
    ):
        raise HTTPException(status_code=404, detail="Not found")
    children = await reader.for_occurrence(occurrence)
    return CoachRosterHealthResponse(
        occurrence_id=occurrence.occurrence_id,
        declared_count=sum(1 for c in children if c.status == "declared"),
        children=[
            CoachChildHealthView(
                student_id=c.student_id,
                full_name=c.full_name,
                status=c.status,
                note=c.note,
                emergency_contact_name=c.emergency_contact_name,
                emergency_contact_phone=c.emergency_contact_phone,
                parent_name=c.parent_name,
                parent_phone=c.parent_phone,
            )
            for c in children
        ],
    )
