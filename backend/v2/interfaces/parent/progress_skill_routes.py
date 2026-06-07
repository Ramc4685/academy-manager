"""Parent skill progress read routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.student_progress.application.errors import StudentNotPlaced
from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
    GetStudentCertificatesCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassportCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent-progress"])


async def _verify_child_ownership(
    parent_id: str,
    student_id: str,
    use_cases: ParentUseCases,
) -> None:
    """Raise 404 if student_id does not belong to parent_id."""
    children = await use_cases.list_children_for_parent(parent_id)  # type: ignore[operator]
    owned = {c["student_id"] for c in children}
    if student_id not in owned:
        raise HTTPException(status_code=404, detail="Student not found")


async def _program_name(use_cases: ParentUseCases, program_id: str) -> str:
    curriculum = use_cases.curriculum
    if curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    program = await curriculum.get_program.execute(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="program not found")
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name") or program_id)
    return getattr(program, "name", None) or program_id


async def _resolve_program_id(use_cases: ParentUseCases, program_id: str | None) -> str:
    if program_id:
        return program_id
    curriculum = use_cases.curriculum
    if curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        program = await curriculum.resolve_default_program.execute()
    except Exception as exc:
        status_code = getattr(exc, "status_code", 409)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if hasattr(program, "model_dump"):
        return str(program.model_dump()["program_id"])
    return program.program_id


@router.get("/students/{student_id}/skill-progress")
async def get_skill_progress(
    student_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> object:
    await _verify_child_ownership(claims.user_id, student_id, use_cases)
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(student_id=student_id, program_id=resolved_program_id)
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"passport": [e.model_dump() for e in entries]}


@router.get("/students/{student_id}/certificates")
async def get_certificates(
    student_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> object:
    await _verify_child_ownership(claims.user_id, student_id, use_cases)
    certs = await use_cases.student_progress.get_certificates.execute(
        GetStudentCertificatesCommand(student_id=student_id)
    )
    return {"certificates": [c.model_dump() for c in certs]}


@router.get("/progress/summary")
async def get_progress_summary(
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    children = await use_cases.list_children_for_parent(claims.user_id)  # type: ignore[operator]
    if not children:
        return {"rows": []}

    program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _program_name(use_cases, program_id)
    rows = [
        await use_cases.student_progress.get_progress_summary.execute(
            ProgressSummaryRequest(
                student_id=str(child["student_id"]),
                student_name=str(child.get("full_name") or child.get("name") or "Unnamed student"),
                program_id=program_id,
                program_name=program_name,
            )
        )
        for child in children
    ]
    return {"rows": [row.model_dump(mode="json") for row in rows]}
