"""Coach lesson plan and progress note routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlanCommand,
    CreateProgressNoteCommand,
    SetProgressNoteVisibilityCommand,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CreateLessonPlanRequest,
    CreateProgressNoteRequest,
    LessonPlanList,
    LessonPlanView,
    ProgressNoteList,
    ProgressNoteView,
    SetNoteVisibilityRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import (
    is_assistant_only,
    is_coach_supervisor,
    require_coach_lead_surface,
    require_coach_surface,
)

router = APIRouter(tags=["coach.notes"])


@router.get("/sessions/{session_id}/lesson-plans", response_model=LessonPlanList)
async def list_lesson_plans(
    session_id: str,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> LessonPlanList:
    rows = await use_cases.list_lesson_plans.execute(claims.user_id, session_id)
    return LessonPlanList(plans=[LessonPlanView(**row.model_dump()) for row in rows])


@router.post("/sessions/{session_id}/lesson-plans", response_model=LessonPlanView)
async def create_lesson_plan(
    session_id: str,
    body: CreateLessonPlanRequest,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> LessonPlanView:
    row = await use_cases.create_lesson_plan.execute(
        CreateLessonPlanCommand(
            coach_id=claims.user_id,
            session_id=session_id,
            title=body.title,
            body=body.body,
        )
    )
    return LessonPlanView(**row.model_dump())


@router.get("/sessions/{session_id}/progress-notes", response_model=ProgressNoteList)
async def list_progress_notes(
    session_id: str,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> ProgressNoteList:
    # Supervisors (owner/admin) see every author's notes for the session;
    # coaches and assistants see only their own.
    rows = await use_cases.list_progress_notes.execute(
        claims.user_id, session_id, all_authors=is_coach_supervisor(claims)
    )
    return ProgressNoteList(notes=[ProgressNoteView(**row.model_dump()) for row in rows])


@router.post("/sessions/{session_id}/progress-notes", response_model=ProgressNoteView)
async def create_progress_note(
    session_id: str,
    body: CreateProgressNoteRequest,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> ProgressNoteView:
    row = await use_cases.create_progress_note.execute(
        CreateProgressNoteCommand(
            coach_id=claims.user_id,
            session_id=session_id,
            student_id=body.student_id,
            body=body.body,
            visibility=body.visibility,
            is_assistant=is_assistant_only(claims),
        )
    )
    return ProgressNoteView(**row.model_dump())


@router.patch(
    "/sessions/{session_id}/progress-notes/{note_id}",
    response_model=ProgressNoteView,
)
async def set_progress_note_visibility(
    session_id: str,
    note_id: str,
    body: SetNoteVisibilityRequest,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> ProgressNoteView:
    """Share a note with the parent or make it private again.

    Stays on ``require_coach_surface``: an assistant may reach it but is
    refused with 403 ``Coaching.NoteShareForbidden`` (a forbidden action on an
    allowed surface, not a wrong-persona 404).
    """
    if use_cases.set_progress_note_visibility is None:
        raise HTTPException(status_code=503, detail="Progress notes service not configured")
    row = await use_cases.set_progress_note_visibility.execute(
        SetProgressNoteVisibilityCommand(
            coach_id=claims.user_id,
            session_id=session_id,
            note_id=note_id,
            visibility=body.visibility,
            is_assistant=is_assistant_only(claims),
            is_supervisor=is_coach_supervisor(claims),
        )
    )
    return ProgressNoteView(**row.model_dump())
