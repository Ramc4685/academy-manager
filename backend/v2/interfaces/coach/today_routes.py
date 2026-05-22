"""GET /api/v2/coach/today — coach's sessions for a date with roster.

Security matrix (docs/security-matrix.md): coach has access to "View
sessions assigned to me." Wrong-persona returns **404** via require_persona.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachRosterEntry,
    CoachSession,
    CoachTodayResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

log = logging.getLogger(__name__)

router = APIRouter(tags=["coach"])


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    return date.fromisoformat(value)


@router.get(
    "/today",
    response_model=CoachTodayResponse,
    summary="Coach's sessions for a date (with roster)",
)
async def get_today(
    on_date: str | None = Query(
        default=None, alias="date", description="YYYY-MM-DD; default = today UTC"
    ),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachTodayResponse:
    target_date = _parse_date(on_date)
    sessions = await use_cases.list_today.execute(claims.user_id, target_date)

    # Fan-out roster fetches concurrently.
    rosters = await asyncio.gather(*[use_cases.get_roster.execute(s.session_id) for s in sessions])

    out = [
        CoachSession(
            session_id=s.session_id,
            occurrence_id=f"{s.session_id}:{s.start_at.isoformat()}",
            title=s.title,
            location=s.location,
            start_at=s.start_at,
            end_at=s.end_at,
            roster=[
                CoachRosterEntry(
                    student_id=r.student_id,
                    full_name=r.full_name,
                    enrollment_status=r.status,
                )
                for r in roster
            ],
        )
        for s, roster in zip(sessions, rosters, strict=False)
    ]
    return CoachTodayResponse(date=target_date.isoformat(), sessions=out)
