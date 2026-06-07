"""Coach skill pathway routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.v2.contexts.coaching.application.use_cases.skill_notes import (
    CreateSkillNoteCommand,
)
from backend.v2.contexts.student_progress.application.errors import StudentNotPlaced
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassportCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
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
    program_id: str | None = None


class CreateSkillNoteBody(BaseModel):
    skill_id: str
    body: str


async def _require_assigned_to_student(
    use_cases: CoachUseCases,
    coach_id: str,
    student_id: str,
    session_id: str | None = None,
) -> str | None:
    enrollments = await use_cases.get_active_session_enrollments_for_student(student_id)
    enrolled_session_ids = [
        str(enrollment.session_id)
        for enrollment in enrollments
        if getattr(enrollment, "session_id", None)
    ]
    if not enrolled_session_ids:
        raise HTTPException(status_code=404, detail="student not found")

    candidate_session_ids = [session_id] if session_id is not None else enrolled_session_ids
    for candidate_session_id in candidate_session_ids:
        if candidate_session_id not in enrolled_session_ids:
            continue
        if await use_cases.assigned_sessions.is_coach_assigned(coach_id, candidate_session_id):
            return candidate_session_id

    raise HTTPException(status_code=404, detail="student not found")


async def _program_name(use_cases: CoachUseCases, program_id: str) -> str:
    curriculum = use_cases.curriculum
    if curriculum is None:
        return program_id
    program = await curriculum.get_program.execute(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="program not found")
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name") or program_id)
    return getattr(program, "name", None) or program_id


async def _resolve_program_id(use_cases: CoachUseCases, program_id: str | None) -> str:
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/students/{student_id}/passport")
async def get_passport(
    student_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(student_id=student_id, program_id=resolved_program_id)
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
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
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
    await _require_assigned_to_student(
        use_cases, claims.user_id, student_id, session_id=body.session_id
    )
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
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    program_id = await _resolve_program_id(use_cases, body.program_id)
    try:
        rec = await use_cases.student_progress.recommend_level_up.execute(
            RecommendLevelUpCommand(
                student_id=student_id,
                program_id=program_id,
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
    session_id = await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    result = await use_cases.create_skill_note.execute(  # type: ignore[union-attr]
        CreateSkillNoteCommand(
            student_id=student_id,
            skill_id=body.skill_id,
            coach_id=claims.user_id,
            session_id=session_id,
            body=body.body,
        ),
        academy_id=claims.academy_id,
    )
    return result.model_dump() if hasattr(result, "model_dump") else result


@router.get("/students/{student_id}/skill-notes")
async def list_skill_notes(
    student_id: str,
    skill_id: str = Query(...),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    results = await use_cases.list_skill_notes.execute(  # type: ignore[union-attr]
        student_id=student_id,
        skill_id=skill_id,
    )
    if isinstance(results, list):
        return {"notes": [r.model_dump() if hasattr(r, "model_dump") else r for r in results]}
    return results


@router.get("/sessions/{session_id}/students-progress")
async def get_session_students_progress(
    session_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _program_name(use_cases, program_id)
    roster = await use_cases.get_roster.execute(session_id)
    rows = [
        await use_cases.student_progress.get_progress_summary.execute(
            ProgressSummaryRequest(
                student_id=entry.student_id,
                student_name=entry.full_name,
                program_id=program_id,
                program_name=program_name,
            )
        )
        for entry in roster
    ]
    return {"rows": [row.model_dump(mode="json") for row in rows]}
