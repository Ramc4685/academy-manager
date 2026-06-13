"""Admin student progress routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.errors import (
    ProgressNextAction,
    RecommendationNotFound,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassportCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    ProgressSummaryRequest,
)
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    SkillBoardRequest,
    SkillBoardStudentRef,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatusCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.ids import new_ulid

router = APIRouter(tags=["admin-progress"])
_PATHWAY_PROGRESS_PAGE_SIZE = 200
_PATHWAY_PROGRESS_MAX_STUDENTS = 5000
_PATHWAY_PROGRESS_CONCURRENCY = 20


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class PlaceStudentBody(BaseModel):
    program_id: str | None = None
    level_id: str
    reason: str | None = None


class RejectLevelUpBody(BaseModel):
    rejection_reason: str | None = None


AdminSettableSkillStatus = Literal[
    "INTRODUCED",
    "LEARNING",
    "PRACTICING",
    "TEST_READY",
    "NEEDS_REVIEW",
]


class UpdateSkillStatusBody(BaseModel):
    level_id: str
    program_id: str
    status: AdminSettableSkillStatus


class RecordTestBody(BaseModel):
    program_id: str
    level_id: str
    attempts_count: int = 1
    success_count: int = 0
    session_id: str | None = None
    notes: str = ""
    coach_override: bool = False
    override_reason: str | None = None


class CoachEngagementStatsRow(BaseModel):
    coach_id: str
    outcomes_recorded: int


class CoachEngagementStatsResponse(BaseModel):
    rows: list[CoachEngagementStatsRow]


def _field(row: object, name: str) -> object:
    if isinstance(row, dict):
        return row[name]
    return getattr(row, name)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/students/{student_id}/place-in-level", status_code=201)
async def place_student(
    student_id: str,
    body: PlaceStudentBody,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    return await _place_student_in_pathway(student_id, body, request, claims, use_cases)


@router.get("/progress/coach-engagement", response_model=CoachEngagementStatsResponse)
async def get_coach_engagement_stats(
    start_date: date = Query(..., description="Inclusive start date, YYYY-MM-DD"),
    end_date: date = Query(..., description="Inclusive end date, YYYY-MM-DD"),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> CoachEngagementStatsResponse:
    use_case = getattr(use_cases, "get_coach_engagement_stats", None)
    if use_case is None:
        raise HTTPException(status_code=503, detail="Coach engagement stats not configured")
    rows = await use_case.execute(start_date=start_date, end_date=end_date)
    return CoachEngagementStatsResponse(
        rows=[
            CoachEngagementStatsRow(
                coach_id=str(_field(row, "coach_id")),
                outcomes_recorded=int(_field(row, "outcomes_recorded")),
            )
            for row in rows
        ]
    )


@router.post("/students/{student_id}/pathway-placement", status_code=201)
async def place_student_pathway(
    student_id: str,
    body: PlaceStudentBody,
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    return await _place_student_in_pathway(student_id, body, request, claims, use_cases)


async def _place_student_in_pathway(
    student_id: str,
    body: PlaceStudentBody,
    request: Request,
    claims: AuthClaims,
    use_cases: AdminUseCases,
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    program_id = await _resolve_program_id(use_cases, body.program_id)
    progress = await use_cases.student_progress.place_student.execute(
        PlaceStudentInLevelCommand(
            student_id=student_id,
            program_id=program_id,
            level_id=body.level_id,
            placed_by=claims.user_id,
            reason=body.reason or "admin_pathway_placement",
        )
    )
    await _write_pathway_placement_audit(
        request,
        claims=claims,
        student_id=student_id,
        program_id=program_id,
        level_id=body.level_id,
        progress_id=progress.progress_id,
        reason=body.reason or "admin_pathway_placement",
    )
    return progress.model_dump()


async def _write_pathway_placement_audit(
    request: Request,
    *,
    claims: AuthClaims,
    student_id: str,
    program_id: str,
    level_id: str,
    progress_id: str,
    reason: str,
) -> None:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return
    await db["audit_logs"].insert_one(
        {
            "audit_id": str(new_ulid()),
            "academy_id": claims.academy_id,
            "actor_id": claims.user_id,
            "action": "student.pathway_placed",
            "entity_type": "student",
            "entity_id": student_id,
            "reason": reason,
            "changed_keys": ["program_id", "level_id", "progress_id"],
            "after": {
                "program_id": program_id,
                "level_id": level_id,
                "progress_id": progress_id,
            },
            "created_at": datetime.now(UTC),
        }
    )


@router.get("/students/{student_id}/progress")
async def get_student_progress(
    student_id: str,
    program_id: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    try:
        result = await use_cases.student_progress.get_student_progress.execute(
            student_id=student_id,
            program_id=resolved_program_id,
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump() if hasattr(result, "model_dump") else result


@router.get("/students/{student_id}/passport")
async def get_student_passport(
    student_id: str,
    program_id: str | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    try:
        entries = await use_cases.student_progress.get_passport.execute(
            GetStudentPassportCommand(student_id=student_id, program_id=resolved_program_id)
        )
    except StudentNotPlaced as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"passport": [entry.model_dump() for entry in entries]}


@router.post("/students/{student_id}/skills/{skill_id}/status")
async def update_admin_skill_status(
    student_id: str,
    skill_id: str,
    body: UpdateSkillStatusBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
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
async def record_admin_skill_test(
    student_id: str,
    skill_id: str,
    body: RecordTestBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
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


async def _resolve_program_id(use_cases: AdminUseCases, program_id: str | None) -> str:
    if program_id:
        return program_id
    curriculum = use_cases.curriculum
    if curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    program = await curriculum.resolve_default_program.execute()
    return program.program_id


@router.get("/pathway/progress")
async def get_pathway_progress_overview(
    program_id: str = Query(...),
    next_action: ProgressNextAction | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    program_name = await _admin_program_name(use_cases, program_id)
    students = await _list_active_admin_students(use_cases)
    summaries = await _build_progress_overviews(
        use_cases=use_cases,
        students=students,
        program_id=program_id,
        program_name=program_name,
    )
    rows = [
        summary
        for summary in summaries
        if next_action is None or summary.next_action == next_action
    ]

    return {"rows": [row.model_dump(mode="json") for row in rows]}


async def _list_active_admin_students(use_cases: AdminUseCases) -> list[object]:
    students: list[object] = []
    cursor: str | None = None
    while True:
        page = await use_cases.list_admin_students.execute(
            search=None,
            status="active",
            limit=_PATHWAY_PROGRESS_PAGE_SIZE,
            cursor=cursor,
        )
        students.extend(page.students)
        if page.next_cursor is None:
            return students
        if len(students) >= _PATHWAY_PROGRESS_MAX_STUDENTS:
            raise HTTPException(
                status_code=413,
                detail="Too many students for one progress overview request",
            )
        cursor = page.next_cursor


async def _build_progress_overviews(
    *,
    use_cases: AdminUseCases,
    students: list[object],
    program_id: str,
    program_name: str,
) -> list[object]:
    limiter = asyncio.Semaphore(_PATHWAY_PROGRESS_CONCURRENCY)

    async def summarize(student: object) -> object:
        async with limiter:
            return await use_cases.student_progress.get_progress_summary.execute(
                ProgressSummaryRequest(
                    student_id=student.student_id,
                    student_name=student.full_name,
                    program_id=program_id,
                    program_name=program_name,
                )
            )

    return await asyncio.gather(*(summarize(student) for student in students))


async def _admin_program_name(use_cases: AdminUseCases, program_id: str) -> str:
    curriculum = use_cases.curriculum
    if curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    program = await curriculum.get_program.execute(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="program not found")
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name") or program_id)
    return getattr(program, "name", None) or program_id


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


# Mirrors coach/skill_routes.py get_session_skill_board (per-persona twin).
@router.get("/sessions/{session_id}/skill-board")
async def get_session_skill_board(
    session_id: str,
    program_id: str | None = Query(None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _admin_program_name(use_cases, resolved_program_id)
    rows = await use_cases.list_admin_enrollments_for_session(session_id)  # type: ignore[operator]
    refs = tuple(
        SkillBoardStudentRef(
            student_id=str(row.get("student_id") or ""),
            student_name=str(row.get("full_name") or row.get("student_name") or "(unknown)"),
        )
        for row in rows
        if row.get("student_id")
    )
    board = await use_cases.student_progress.get_skill_board.execute(
        SkillBoardRequest(
            students=refs,
            program_id=resolved_program_id,
            program_name=program_name,
        )
    )
    return board.model_dump(mode="json")
