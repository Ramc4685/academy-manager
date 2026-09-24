"""GET /api/v2/coach/today — coach's sessions for a date with roster.

Security matrix (docs/security-matrix.md): coach has access to "View
sessions assigned to me." Wrong-persona returns **404** via
require_coach_surface. A coach supervisor (academy admin/owner, #632) gets
every session in the academy for the date, each labelled with its coach.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from backend.v2.interfaces.coach.deps import CoachUseCases, coach_names_for, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachRosterEntry,
    CoachSession,
    CoachTodayResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

log = logging.getLogger(__name__)

router = APIRouter(tags=["coach"])


async def _resolve_date(
    value: str | None,
    *,
    academy_id: str,
    use_cases: CoachUseCases,
) -> date:
    if value is not None:
        return date.fromisoformat(value)
    # Default "today" to the academy-local calendar date, not UTC, so a
    # coach checking in during an evening class (past UTC midnight) still
    # sees today's sessions (#510). Falls back to UTC when the academy has
    # no timezone configured or the lookup isn't composed.
    lookup = getattr(use_cases, "get_academy_timezone", None)
    if lookup is not None:
        try:
            timezone_name = await lookup(academy_id)
            if timezone_name:
                return datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()
        except (KeyError, ValueError):
            log.warning("Invalid academy timezone for %s; defaulting to UTC", academy_id)
    return datetime.now(UTC).date()


async def _read_overdue_cents(
    reader: Any,
    rosters: Sequence[Sequence[Any]],
    on_date: date,
) -> dict[str, int]:
    """Overdue cents per student, never at the cost of the coach's day.

    A billing read that fails must not take down ``/coach/today`` — the chip
    is a nicety, the roster is the job — so an error degrades to "no chip".
    """
    student_ids = [r.student_id for roster in rosters for r in roster]
    if not student_ids:
        return {}
    try:
        result: dict[str, int] = await reader(student_ids, on_date)
        return result
    except Exception:
        log.warning("coach roster overdue lookup failed; hiding payment chips", exc_info=True)
        return {}


@router.get(
    "/today",
    response_model=CoachTodayResponse,
    summary="Coach's sessions for a date (with roster)",
)
async def get_today(
    on_date: str | None = Query(
        default=None,
        alias="date",
        description="YYYY-MM-DD; default = today in the academy timezone",
    ),
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachTodayResponse:
    target_date = await _resolve_date(on_date, academy_id=claims.academy_id, use_cases=use_cases)
    supervisor = is_coach_supervisor(claims)
    # Cancelled classes stay on the coach's day (#777) — struck through with
    # the reason by the client — so nobody drives to a called-off class.
    if supervisor:
        sessions = await use_cases.list_today.execute_for_academy(
            target_date, include_cancelled=True
        )
    else:
        sessions = await use_cases.list_today.execute(
            claims.user_id, target_date, include_cancelled=True
        )
    coach_names = await coach_names_for(sessions, use_cases=use_cases, supervisor=supervisor)

    # Fan-out roster fetches concurrently. Prefer the occurrence-scoped
    # roster (expected-absence flags + one-time makeup/trial entries) when
    # composed; fall back to the plain session roster for test fixtures
    # that predate it.
    get_occurrence_roster = getattr(use_cases, "get_occurrence_roster", None)
    if get_occurrence_roster is not None:
        rosters = await asyncio.gather(
            *[
                get_occurrence_roster.execute(
                    session_id=s.roster_session_id, occurrence_id=s.occurrence_id
                )
                for s in sessions
            ]
        )
    else:
        rosters = await asyncio.gather(
            *[use_cases.get_roster.execute(s.roster_session_id) for s in sessions]
        )

    # Existing marks per occurrence, so a reload doesn't present a marked
    # class as unmarked (and "Mark all present" doesn't re-send marked rows,
    # which the bulk endpoint rejects whole-batch with 409).
    list_attendance = getattr(use_cases, "list_attendance_for_occurrence", None)
    marks_by_occurrence: dict[str, dict[str, str]] = {}
    if list_attendance is not None:
        attendance_lists = await asyncio.gather(
            *[list_attendance(s.occurrence_id) for s in sessions]
        )
        for s, marks in zip(sessions, attendance_lists, strict=False):
            marks_by_occurrence[s.occurrence_id] = {m.student_id: m.status for m in marks}

    # Issue #774: one money fact per roster row. Resolved in a single query
    # across every student on the day's rosters, so the chip costs one read
    # regardless of how many sessions the coach is teaching.
    overdue_reader = getattr(use_cases, "overdue_cents_by_student", None)
    overdue_cents: dict[str, int] = {}
    if callable(overdue_reader):
        overdue_cents = await _read_overdue_cents(overdue_reader, rosters, target_date)

    out = [
        CoachSession(
            session_id=s.session_id,
            occurrence_id=s.occurrence_id,
            title=s.title,
            location=s.location,
            timezone=s.timezone,
            start_at=s.start_at,
            end_at=s.end_at,
            coach_id=getattr(s, "coach_id", None),
            coach_name=coach_names.get(getattr(s, "coach_id", None) or ""),
            status=getattr(s, "status", "scheduled"),
            cancellation_reason=getattr(s, "cancellation_reason", None),
            roster=[
                CoachRosterEntry(
                    student_id=r.student_id,
                    full_name=r.full_name,
                    enrollment_status=r.status,
                    attendance_status=marks_by_occurrence.get(s.occurrence_id, {}).get(
                        r.student_id
                    ),
                    expected_absence=getattr(r, "expected_absence", False),
                    entry_source=getattr(r, "entry_source", "enrollment"),
                    trial_request_id=getattr(r, "trial_request_id", None),
                    trial_outcome=getattr(r, "trial_outcome", None),
                    pending_cancellation_at=getattr(r, "pending_cancellation_at", None),
                    hold_return_on=getattr(r, "hold_return_on", None),
                    payment_due_cents=overdue_cents.get(r.student_id) or None,
                )
                for r in roster
            ],
        )
        for s, roster in zip(sessions, rosters, strict=False)
    ]
    return CoachTodayResponse(date=target_date.isoformat(), sessions=out)
