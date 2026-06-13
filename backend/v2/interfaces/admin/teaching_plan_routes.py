"""Admin BFF: read-only teaching-plan visibility for session occurrences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    LevelTeachingGroup,
    UnplacedStudent,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-teaching-plan"])


class AdminOccurrenceTeachingPlanResponse(BaseModel):
    program_id: str = ""
    program_name: str = ""
    pathway_configured: bool = False
    occurrence_id: str
    session_id: str
    coach_id: str
    groups: list[LevelTeachingGroup] = Field(default_factory=list)
    unplaced: list[UnplacedStudent] = Field(default_factory=list)


def _id_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("program_id", ""))
    return str(getattr(program, "program_id", "") or "")


def _name_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name", "") or "")
    return str(getattr(program, "name", "") or "")


async def _resolve_program_graceful(
    use_cases: AdminUseCases, program_id: str | None
) -> tuple[str | None, str]:
    curriculum = getattr(use_cases, "curriculum", None)
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


def _assigned_coach_id(occurrence: Any) -> str:
    return str(
        getattr(occurrence, "actual_coach_id", None)
        or getattr(occurrence, "substitute_coach_id", None)
        or getattr(occurrence, "scheduled_coach_id", "")
    )


@router.get(
    "/sessions/{occurrence_id}/teaching-plan",
    response_model=AdminOccurrenceTeachingPlanResponse,
    summary="Admin read-only teaching plan for a session occurrence",
)
async def get_occurrence_teaching_plan(
    occurrence_id: str,
    program_id: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminOccurrenceTeachingPlanResponse:
    plan_use_case = getattr(use_cases, "generate_daily_teaching_plan", None)
    get_occurrence = getattr(use_cases, "get_session_occurrence", None)
    if plan_use_case is None or get_occurrence is None:
        raise HTTPException(status_code=503, detail="Teaching plan service not configured")

    occurrence = await get_occurrence(occurrence_id)
    if occurrence is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    resolved_id, program_name = await _resolve_program_graceful(use_cases, program_id)
    session_id = str(getattr(occurrence, "session_id", ""))
    groups = await plan_use_case.build_session_groups(
        session_id=session_id,
        program_id=resolved_id,
    )
    return AdminOccurrenceTeachingPlanResponse(
        program_id=resolved_id or "",
        program_name=program_name,
        pathway_configured=bool(resolved_id),
        occurrence_id=str(getattr(occurrence, "occurrence_id", occurrence_id)),
        session_id=session_id,
        coach_id=_assigned_coach_id(occurrence),
        groups=groups.groups,
        unplaced=groups.unplaced,
    )
