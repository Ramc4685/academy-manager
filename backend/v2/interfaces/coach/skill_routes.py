"""Coach skill pathway routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassportCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatusCommand,
)
from backend.v2.contexts.student_progress.application.errors import StudentNotPlaced
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["coach-skills"])


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class UpdateStatusBody(BaseModel):
    level_id: str
    program_id: str
    status: str  # e.g. "IN_PROGRESS", "PASSED", "NOT_STARTED"
    introduced_at: str | None = None


class RecordTestBody(BaseModel):
    program_id: str
    level_id: str
    attempts_count: int = 1
    success_count: int = 0
    session_id: str | None = None
    notes: str = ""
    coach_override: bool = False
    override_reason: str | None = None


class RecommendLevelUpBody(BaseModel):
    program_id: str


class CreateSkillNoteBody(BaseModel):
    skill_id: str
    body: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/students/{student_id}/passport")
async def get_passport(
    student_id: str,
    program_id: str = Query(...),
    _claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(student_id=student_id, program_id=program_id)
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"passport": [e.model_dump() for e in entries]}


@router.post("/students/{student_id}/skills/{skill_id}/status")
async def update_skill_status(
    student_id: str,
    skill_id: str,
    body: UpdateStatusBody,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    try:
        result = await use_cases.student_progress.update_skill_status.execute(
            UpdateSkillStatusCommand(
                student_id=student_id,
                skill_id=skill_id,
                level_id=body.level_id,
                program_id=body.program_id,
                new_status=body.status,  # type: ignore[arg-type]
                updated_by=claims.user_id,
            )
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


@router.post("/students/{student_id}/skills/{skill_id}/test", status_code=201)
async def record_test(
    student_id: str,
    skill_id: str,
    body: RecordTestBody,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    try:
        result = await use_cases.student_progress.record_test_attempt.execute(
            RecordTestAttemptCommand(
                student_id=student_id,
                skill_id=skill_id,
                program_id=body.program_id,
                level_id=body.level_id,
                coach_id=claims.user_id,
                session_id=body.session_id,
                attempts_count=body.attempts_count,
                success_count=body.success_count,
                notes=body.notes,
                coach_override=body.coach_override,
                override_reason=body.override_reason,
            )
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump()


@router.post("/students/{student_id}/level-up", status_code=201)
async def recommend_level_up(
    student_id: str,
    body: RecommendLevelUpBody,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    try:
        rec = await use_cases.student_progress.recommend_level_up.execute(
            RecommendLevelUpCommand(
                student_id=student_id,
                program_id=body.program_id,
                recommended_by=claims.user_id,
            )
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return rec.model_dump()


@router.post("/students/{student_id}/skill-notes", status_code=201)
async def create_skill_note(
    student_id: str,
    body: CreateSkillNoteBody,
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    result = await use_cases.create_skill_note.execute(  # type: ignore[union-attr]
        student_id=student_id,
        skill_id=body.skill_id,
        coach_id=claims.user_id,
        body=body.body,
    )
    return result.model_dump() if hasattr(result, "model_dump") else result


@router.get("/students/{student_id}/skill-notes")
async def list_skill_notes(
    student_id: str,
    skill_id: str = Query(...),
    _claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    results = await use_cases.list_skill_notes.execute(  # type: ignore[union-attr]
        student_id=student_id,
        skill_id=skill_id,
    )
    if isinstance(results, list):
        return {"notes": [r.model_dump() if hasattr(r, "model_dump") else r for r in results]}
    return results
