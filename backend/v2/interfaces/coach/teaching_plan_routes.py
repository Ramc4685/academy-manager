"""Coach BFF: daily teaching plan (lesson guidance).

Security matrix (docs/security-matrix.md): coach may view sessions assigned to
them. Wrong-persona returns **404** via ``require_persona``. The plan endpoints
never 5xx on a missing pathway — they return ``pathway_configured: false`` with
empty groups. ``503`` is reserved for a missing teaching-plan composition.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import CoachSessionTeachingPlanResponse
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

log = logging.getLogger(__name__)

router = APIRouter(tags=["coach-teaching-plan"])


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    return date.fromisoformat(value)


def _id_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("program_id", ""))
    return str(getattr(program, "program_id", ""))


def _name_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name", "") or "")
    return str(getattr(program, "name", "") or "")


async def _resolve_program_graceful(
    use_cases: CoachUseCases, program_id: str | None
) -> tuple[str | None, str]:
    """Resolve ``(program_id, program_name)``.

    Returns ``(None, "")`` when no pathway is configured (no explicit program
    and no active default program) so the plan degrades to
    ``pathway_configured: false`` instead of 5xx.
    """
    curriculum = use_cases.curriculum
    if curriculum is None:
        return None, ""

    resolved_id = program_id
    if not resolved_id:
        try:
            program = await curriculum.resolve_default_program.execute()
        except Exception:
            return None, ""
        resolved_id = _id_of(program)
        if not resolved_id:
            return None, ""

    name = ""
    try:
        program = await curriculum.get_program.execute(resolved_id)
        if program is not None:
            name = _name_of(program)
    except Exception:
        name = ""
    return resolved_id, name


@router.get("/today/plan", summary="Coach's teaching plan for all sessions on a date")
async def get_today_plan(
    on_date: str | None = Query(
        default=None, alias="date", description="YYYY-MM-DD; default = today UTC"
    ),
    program_id: str | None = Query(default=None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> dict[str, Any]:
    if use_cases.generate_daily_teaching_plan is None:
        raise HTTPException(status_code=503, detail="Teaching plan service not configured")

    target_date = _parse_date(on_date)
    resolved_id, program_name = await _resolve_program_graceful(use_cases, program_id)
    plan = await use_cases.generate_daily_teaching_plan.execute(
        coach_id=claims.user_id,
        on_date=target_date,
        program_id=resolved_id,
        program_name=program_name,
    )
    return plan.model_dump(mode="json")


@router.get(
    "/sessions/{session_id}/teaching-plan",
    summary="Coach's teaching plan for a single session",
)
async def get_session_teaching_plan(
    session_id: str,
    program_id: str | None = Query(default=None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> dict[str, Any]:
    if use_cases.generate_daily_teaching_plan is None:
        raise HTTPException(status_code=503, detail="Teaching plan service not configured")
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    resolved_id, program_name = await _resolve_program_graceful(use_cases, program_id)
    groups = await use_cases.generate_daily_teaching_plan.build_session_groups(
        session_id=session_id, program_id=resolved_id
    )
    return CoachSessionTeachingPlanResponse(
        program_id=resolved_id or "",
        program_name=program_name,
        pathway_configured=bool(resolved_id),
        session_id=session_id,
        groups=groups.groups,
        unplaced=groups.unplaced,
    ).model_dump(mode="json")
