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


@router.get("/students/{student_id}/skill-progress")
async def get_skill_progress(
    student_id: str,
    program_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> object:
    await _verify_child_ownership(claims.user_id, student_id, use_cases)
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(student_id=student_id, program_id=program_id)
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
