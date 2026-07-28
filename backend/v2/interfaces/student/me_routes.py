"""Student's own profile — name, academy, level (UIM12)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
)
from backend.v2.interfaces.student.deps import (
    ResolvedStudent,
    StudentUseCases,
    get_resolved_student,
    get_student_use_cases,
)
from backend.v2.interfaces.student.views import StudentMeView

log = logging.getLogger(__name__)

router = APIRouter(tags=["student.me"])


async def _current_level_name(use_cases: StudentUseCases, resolved: ResolvedStudent) -> str | None:
    """Best-effort level lookup — reuses the same progress-summary use case
    the parent portal's `GET /parent/progress/summary` uses. Progress not
    being configured, or the student not yet being placed in a level, are
    both normal states for a small read like `/student/me`: return `None`
    rather than failing the whole profile read.
    """
    curriculum = use_cases.curriculum
    progress = use_cases.student_progress
    if curriculum is None or progress is None:
        return None
    try:
        program = await curriculum.resolve_default_program.execute()
        program_id = (
            program.model_dump()["program_id"]
            if hasattr(program, "model_dump")
            else program.program_id
        )
        program_name = (
            program.model_dump().get("name", program_id)
            if hasattr(program, "model_dump")
            else getattr(program, "name", program_id)
        )
        row = await progress.get_progress_summary.execute(
            ProgressSummaryRequest(
                student_id=resolved.student_id,
                student_name=resolved.full_name,
                program_id=str(program_id),
                program_name=str(program_name),
            )
        )
        return getattr(row, "current_level_name", None)
    except Exception:
        log.debug("student.me level lookup skipped", exc_info=True)
        return None


@router.get("/me", response_model=StudentMeView)
async def get_my_profile(
    resolved: ResolvedStudent = Depends(get_resolved_student),
    use_cases: StudentUseCases = Depends(get_student_use_cases),
) -> StudentMeView:
    academy_info = await use_cases.get_academy_info(academy_id=resolved.academy_id)  # type: ignore[operator]
    level = await _current_level_name(use_cases, resolved)
    return StudentMeView(
        student_id=resolved.student_id,
        full_name=resolved.full_name,
        academy_id=resolved.academy_id,
        academy_name=str(academy_info.get("display_name") or "Academy"),
        level=level,
    )
