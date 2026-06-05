"""Admin student progress routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
)
from backend.v2.contexts.student_progress.domain.errors import (
    RecommendationNotFound,
    StudentNotPlaced,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-progress"])


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class PlaceStudentBody(BaseModel):
    program_id: str
    level_id: str


class RejectLevelUpBody(BaseModel):
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/students/{student_id}/place-in-level", status_code=201)
async def place_student(
    student_id: str,
    body: PlaceStudentBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    progress = await use_cases.student_progress.place_student.execute(
        PlaceStudentInLevelCommand(
            student_id=student_id,
            program_id=body.program_id,
            level_id=body.level_id,
            placed_by=claims.user_id,
        )
    )
    return progress.model_dump()


@router.get("/students/{student_id}/progress")
async def get_student_progress(
    student_id: str,
    program_id: str = Query(...),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    try:
        result = await use_cases.student_progress.get_student_progress.execute(
            student_id=student_id,
            program_id=program_id,
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump() if hasattr(result, "model_dump") else result


@router.get("/level-up-queue")
async def get_level_up_queue(
    program_id: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
        GetLevelUpQueueCommand,
    )

    queue = await use_cases.student_progress.get_level_up_queue.execute(
        GetLevelUpQueueCommand(program_id=program_id)
    )
    return {"queue": [rec.model_dump() for rec in queue]}


@router.post("/level-up/{rec_id}/approve")
async def approve_level_up(
    rec_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    try:
        result = await use_cases.student_progress.review_level_up.execute(
            ReviewLevelUpCommand(
                rec_id=rec_id,
                action="approve",
                reviewed_by=claims.user_id,
            )
        )
    except RecommendationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


@router.post("/level-up/{rec_id}/reject")
async def reject_level_up(
    rec_id: str,
    body: RejectLevelUpBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    try:
        result = await use_cases.student_progress.review_level_up.execute(
            ReviewLevelUpCommand(
                rec_id=rec_id,
                action="reject",
                reviewed_by=claims.user_id,
                rejection_reason=body.rejection_reason,
            )
        )
    except RecommendationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


@router.get("/students/{student_id}/certificates")
async def get_certificates(
    student_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
        GetStudentCertificatesCommand,
    )

    certs = await use_cases.student_progress.get_certificates.execute(
        GetStudentCertificatesCommand(student_id=student_id)
    )
    return {"certificates": [c.model_dump() for c in certs]}
