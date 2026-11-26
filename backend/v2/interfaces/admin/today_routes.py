"""Admin Today (S63, decisions D-20 and D-14).

* ``GET /admin/today?date=YYYY-MM-DD``: the academy's class dates on its own
  calendar day (default today) with rosters, parent phones and attendance
  state. No health field, ever.
* ``GET /admin/today/roster-health?occurrence_id=...``: the health marker for
  one class date, read through the coach S49 reader. ``Cache-Control:
  no-store``; 404 for a class date of another academy.

``require_persona("admin")`` (admins and owners). Services at
``app.state.admin_today`` (``composition/admin_today.py``).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.v2.composition.admin_today import AdminToday, AdminTodayReader
from backend.v2.composition.coach_roster_health import HealthStatus
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.today"])


def get_admin_today(request: Request) -> AdminTodayReader:
    reader: AdminTodayReader = request.app.state.admin_today
    return reader


class AdminChildHealthView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str
    status: HealthStatus
    note: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class AdminRosterHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: str
    declared_count: int
    children: list[AdminChildHealthView]


@router.get("/today", response_model=AdminToday, summary="Today's classes with rosters")
async def get_today(
    on_date: date | None = Query(default=None, alias="date"),
    _claims: AuthClaims = Depends(require_persona("admin")),
    reader: AdminTodayReader = Depends(get_admin_today),
) -> AdminToday:
    return await reader.today(on_date)


@router.get(
    "/today/roster-health",
    response_model=AdminRosterHealthResponse,
    summary="Health notes for one class date (never cached)",
)
async def get_today_roster_health(
    response: Response,
    occurrence_id: str = Query(min_length=1, max_length=128),
    _claims: AuthClaims = Depends(require_persona("admin")),
    reader: AdminTodayReader = Depends(get_admin_today),
) -> AdminRosterHealthResponse:
    response.headers["Cache-Control"] = "no-store"
    occurrence = await reader.health.occurrence(occurrence_id)
    if occurrence is None:
        raise HTTPException(status_code=404, detail="Not found")
    children = await reader.health.for_occurrence(occurrence)
    return AdminRosterHealthResponse(
        occurrence_id=occurrence.occurrence_id,
        declared_count=sum(1 for c in children if c.status == "declared"),
        children=[
            AdminChildHealthView(
                student_id=c.student_id,
                status=c.status,
                note=c.note,
                emergency_contact_name=c.emergency_contact_name,
                emergency_contact_phone=c.emergency_contact_phone,
            )
            for c in children
        ],
    )
