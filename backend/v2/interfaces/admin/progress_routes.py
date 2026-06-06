"""Admin student progress routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.errors import (
    RecommendationNotFound,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
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

    # Resolve certificate display fields up front (the use case stays pure — it
    # receives the already-resolved names). The pending recommendation carries
    # the student/program/from-level ids we need to look those names up.
    display = await _resolve_certificate_display(rec_id, use_cases)

    try:
        result = await use_cases.student_progress.review_level_up.execute(
            ReviewLevelUpCommand(
                rec_id=rec_id,
                action="approve",
                reviewed_by=claims.user_id,
                student_name=display["student_name"],
                level_name=display["level_name"],
                program_name=display["program_name"],
                level_sequence=display["level_sequence"],
            )
        )
    except RecommendationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


async def _resolve_certificate_display(rec_id: str, use_cases: AdminUseCases) -> dict[str, object]:
    """Best-effort lookup of certificate display fields for a pending rec.

    Uses only the existing admin composition surface. Falls back to blank
    names / sequence 1 if anything is unavailable so approval never fails on a
    cosmetic lookup.
    """
    from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
        GetLevelUpQueueCommand,
    )

    display: dict[str, object] = {
        "student_name": "",
        "level_name": "",
        "program_name": "",
        "level_sequence": 1,
    }
    if use_cases.student_progress is None:
        return display

    queue = await use_cases.student_progress.get_level_up_queue.execute(GetLevelUpQueueCommand())
    rec = next((r for r in queue if r.rec_id == rec_id), None)
    if rec is None:
        return display

    if use_cases.get_admin_student is not None:
        student = await use_cases.get_admin_student.execute(rec.student_id)
        display["student_name"] = getattr(student, "full_name", "") or ""

    if use_cases.curriculum is not None:
        program = await use_cases.curriculum.get_program.execute(rec.program_id)
        display["program_name"] = getattr(program, "name", "") or ""
        levels = await use_cases.curriculum.list_levels.execute(rec.program_id)
        level = next((lv for lv in levels if lv.level_id == rec.from_level_id), None)
        if level is not None:
            display["level_name"] = level.name
            display["level_sequence"] = level.sequence

    return display


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
