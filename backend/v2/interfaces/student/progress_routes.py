"""Student's own skill progress (UIM12).

Reuses the same `StudentProgressComposition`/`CurriculumComposition`
instances the parent BFF's `progress_skill_routes.py` uses — wired in
`composition/student.py`. No ownership check is needed here (unlike the
parent routes' `_verify_child_ownership`): `resolved.student_id` already
comes from the caller's own `student_user_id` link, so there is nothing to
verify against — the trust boundary is the link itself.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.student_progress.application.errors import StudentNotPlaced
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassportCommand,
)
from backend.v2.interfaces.student.deps import (
    ResolvedStudent,
    StudentUseCases,
    get_resolved_student,
    get_student_use_cases,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["student.progress"])


async def _resolve_program_id(use_cases: StudentUseCases, program_id: str | None) -> str:
    if program_id:
        return program_id
    curriculum = use_cases.curriculum
    if curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        program = await curriculum.resolve_default_program.execute()
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            log.exception("Failed to resolve default curriculum program")
            raise HTTPException(
                status_code=503,
                detail="Progress is temporarily unavailable. Please try again shortly.",
            ) from exc
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if hasattr(program, "model_dump"):
        return str(program.model_dump()["program_id"])
    return program.program_id


@router.get("/progress")
async def get_my_progress(
    program_id: str | None = Query(None),
    resolved: ResolvedStudent = Depends(get_resolved_student),
    use_cases: StudentUseCases = Depends(get_student_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(
                student_id=resolved.student_id, program_id=resolved_program_id
            )
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"passport": [e.model_dump() for e in entries]}
