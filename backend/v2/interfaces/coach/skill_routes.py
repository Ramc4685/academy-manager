"""Coach skill pathway routes."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator

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
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    SkillBoardRequest,
    SkillBoardStudentRef,
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

log = logging.getLogger(__name__)

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
    # Client-generated ULID; retries with the same id return the original
    # result instead of recording a duplicate attempt.
    mutation_id: str | None = None

    @model_validator(mode="after")
    def _success_not_above_attempts(self) -> RecordTestBody:
        if self.success_count > self.attempts_count:
            raise ValueError("success_count cannot exceed attempts_count")
        return self


class RecommendLevelUpBody(BaseModel):
    program_id: str | None = None


class CreateSkillNoteBody(BaseModel):
    skill_id: str
    body: str


class BulkStatusBody(BaseModel):
    skill_id: str
    program_id: str
    level_id: str
    student_ids: list[str]
    status: str


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    return date.fromisoformat(value)


def _dump(value: object) -> dict[str, object]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[no-any-return]
    if isinstance(value, dict):
        return value
    return dict(getattr(value, "_values", {}))


def _skill_value(skill: dict[str, object], key: str, fallback: object = "") -> object:
    return skill.get(key, fallback)


def _skill_name(skill: dict[str, object]) -> str:
    value = _skill_value(skill, "skill_name", None) or _skill_value(skill, "name", None)
    return str(value or _skill_value(skill, "skill_id", "Skill"))


def _is_skill_gap(skill: dict[str, object]) -> bool:
    return str(_skill_value(skill, "status", "NOT_STARTED")) != "PASSED"


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
        # Curated domain errors carry their own status_code and a user-safe
        # message; surface those. Anything else is unexpected — log it and
        # return a generic message so raw internal text never reaches the user.
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            log.exception("Failed to resolve default curriculum program")
            raise HTTPException(
                status_code=503,
                detail="Curriculum is temporarily unavailable. Please try again shortly.",
            ) from exc
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if hasattr(program, "model_dump"):
        return str(program.model_dump()["program_id"])
    return program.program_id


async def _session_for_request(
    use_cases: CoachUseCases,
    coach_id: str,
    session_or_occurrence_id: str,
    on_date: date | None,
) -> object:
    if on_date is not None:
        sessions = await use_cases.list_today.execute(coach_id, on_date)
        for session in sessions:
            if session_or_occurrence_id in (
                str(getattr(session, "session_id", "")),
                str(getattr(session, "occurrence_id", "")),
            ):
                return session

    if not await use_cases.assigned_sessions.is_coach_assigned(coach_id, session_or_occurrence_id):
        raise HTTPException(status_code=404, detail="session not found")
    return type(
        "CoachSessionRef",
        (),
        {
            "session_id": session_or_occurrence_id,
            "occurrence_id": session_or_occurrence_id,
            "roster_session_id": session_or_occurrence_id,
            "title": session_or_occurrence_id,
            "location": "",
            "timezone": None,
            "start_at": None,
            "end_at": None,
        },
    )()


async def _build_session_skills(
    use_cases: CoachUseCases,
    *,
    coach_id: str,
    session: object,
    program_id: str,
) -> dict[str, object]:
    session_id = str(session.session_id)
    roster_session_id = str(getattr(session, "roster_session_id", session_id))
    if not await use_cases.assigned_sessions.is_coach_assigned(coach_id, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")

    roster = await use_cases.get_roster.execute(roster_session_id)
    students: list[dict[str, object]] = []
    grouped: dict[str, dict[str, object]] = {}

    for entry in roster:
        try:
            passport_entries = await use_cases.student_progress.get_passport.execute(
                GetStudentPassportCommand(student_id=entry.student_id, program_id=program_id)
            )
        except StudentNotPlaced:
            passport_entries = []
        skills = [_dump(skill) for skill in passport_entries]
        gap_skills = [skill for skill in skills if _is_skill_gap(skill)]
        students.append(
            {
                "student_id": entry.student_id,
                "full_name": entry.full_name,
                "enrollment_status": entry.status,
                "skills": [
                    {
                        "skill_id": str(_skill_value(skill, "skill_id")),
                        "skill_name": _skill_name(skill),
                        "status": str(_skill_value(skill, "status", "NOT_STARTED")),
                        "program_id": str(_skill_value(skill, "program_id", program_id)),
                        "level_id": str(_skill_value(skill, "level_id", "")),
                    }
                    for skill in skills
                ],
                "top_gaps": [
                    {
                        "skill_id": str(_skill_value(skill, "skill_id")),
                        "skill_name": _skill_name(skill),
                        "status": str(_skill_value(skill, "status", "NOT_STARTED")),
                        "program_id": str(_skill_value(skill, "program_id", program_id)),
                        "level_id": str(_skill_value(skill, "level_id", "")),
                    }
                    for skill in gap_skills[:3]
                ],
            }
        )
        for skill in gap_skills:
            skill_id = str(_skill_value(skill, "skill_id"))
            group = grouped.setdefault(
                skill_id,
                {
                    "skill_id": skill_id,
                    "skill_name": _skill_name(skill),
                    "student_ids": [],
                    "student_names": [],
                    "status": str(_skill_value(skill, "status", "NOT_STARTED")),
                },
            )
            group["student_ids"].append(entry.student_id)
            group["student_names"].append(entry.full_name)

    return {
        "session_id": session_id,
        "occurrence_id": str(getattr(session, "occurrence_id", session_id)),
        "title": str(getattr(session, "title", session_id)),
        "location": str(getattr(session, "location", "")),
        "timezone": getattr(session, "timezone", None),
        "start_at": getattr(session, "start_at", None),
        "end_at": getattr(session, "end_at", None),
        "roster": [
            {
                "student_id": entry.student_id,
                "full_name": entry.full_name,
                "enrollment_status": entry.status,
            }
            for entry in roster
        ],
        "skill_groups": list(grouped.values()),
        "students": students,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/day-hub")
async def get_day_hub(
    on_date: str | None = Query(None, alias="date"),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    target_date = _parse_date(on_date)
    program_id = await _resolve_program_id(use_cases, None)
    sessions = await use_cases.list_today.execute(claims.user_id, target_date)
    session_models = [
        await _build_session_skills(
            use_cases,
            coach_id=claims.user_id,
            session=session,
            program_id=program_id,
        )
        for session in sessions
    ]
    student_ids = {
        str(student["student_id"]) for session in session_models for student in session["roster"]
    }
    skill_focus_count = sum(len(session["skill_groups"]) for session in session_models)
    return {
        "date": target_date.isoformat(),
        "summary": {
            "session_count": len(session_models),
            "student_count": len(student_ids),
            "attendance_state": "not_started" if session_models else "no_sessions",
            "skill_focus_count": skill_focus_count,
            "parent_message_count": 0,
            "absence_notice_count": 0,
        },
        "sessions": session_models,
    }


@router.get("/sessions/{session_id}/skills")
async def get_session_skills(
    session_id: str,
    on_date: str | None = Query(None, alias="date"),
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    target_date = _parse_date(on_date) if on_date else None
    session = await _session_for_request(use_cases, claims.user_id, session_id, target_date)
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    model = await _build_session_skills(
        use_cases,
        coach_id=claims.user_id,
        session=session,
        program_id=resolved_program_id,
    )
    model["date"] = target_date.isoformat() if target_date else None
    return model


@router.post("/sessions/{session_id}/skills/bulk-status")
async def bulk_update_skill_status(
    session_id: str,
    body: BulkStatusBody,
    on_date: str | None = Query(None, alias="date"),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    target_date = _parse_date(on_date) if on_date else None
    session = await _session_for_request(use_cases, claims.user_id, session_id, target_date)
    resolved_session_id = str(session.session_id)
    roster_session_id = str(getattr(session, "roster_session_id", resolved_session_id))
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, resolved_session_id):
        raise HTTPException(status_code=404, detail="session not found")

    roster = await use_cases.get_roster.execute(roster_session_id)
    allowed_student_ids = {entry.student_id for entry in roster}
    selected_student_ids = list(dict.fromkeys(body.student_ids))
    if not selected_student_ids or any(
        student_id not in allowed_student_ids for student_id in selected_student_ids
    ):
        raise HTTPException(status_code=404, detail="student not found")

    for student_id in selected_student_ids:
        await use_cases.student_progress.update_skill_status.execute(
            UpdateSkillStatusCommand(
                student_id=student_id,
                skill_id=body.skill_id,
                level_id=body.level_id,
                program_id=body.program_id,
                new_status=body.status,
                updated_by=claims.user_id,
            )
        )
    return {"updated": len(selected_student_ids), "student_ids": selected_student_ids}


@router.get("/students/{student_id}/passport")
async def get_passport(
    student_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
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
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    try:
        result = await use_cases.student_progress.update_skill_status.execute(
            UpdateSkillStatusCommand(
                student_id=student_id,
                skill_id=skill_id,
                level_id=body.level_id,
                program_id=body.program_id,
                new_status=body.status,
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
                mutation_id=body.mutation_id,
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
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
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
    if use_cases.create_skill_note is None:
        raise HTTPException(status_code=503, detail="Skill notes service not configured")
    result = await use_cases.create_skill_note.execute(
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
    if use_cases.list_skill_notes is None:
        raise HTTPException(status_code=503, detail="Skill notes service not configured")
    results = await use_cases.list_skill_notes.execute(
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


# Mirrors admin/progress_routes.py get_session_skill_board (per-persona twin).
@router.get("/sessions/{session_id}/skill-board")
async def get_session_skill_board(
    session_id: str,
    program_id: str | None = Query(None),
    claims: AuthClaims = Depends(require_persona("coach")),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> object:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    if not await use_cases.assigned_sessions.is_coach_assigned(claims.user_id, session_id):
        raise HTTPException(status_code=404, detail="session not found")

    resolved_program_id = await _resolve_program_id(use_cases, program_id)
    program_name = await _program_name(use_cases, resolved_program_id)
    roster = await use_cases.get_roster.execute(session_id)
    board = await use_cases.student_progress.get_skill_board.execute(
        SkillBoardRequest(
            students=tuple(
                SkillBoardStudentRef(student_id=entry.student_id, student_name=entry.full_name)
                for entry in roster
            ),
            program_id=resolved_program_id,
            program_name=program_name,
        )
    )
    return board.model_dump(mode="json")
