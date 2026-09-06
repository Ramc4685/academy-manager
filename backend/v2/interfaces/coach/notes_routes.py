"""Coach lesson plan and progress note routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlanCommand,
    CreateProgressNoteCommand,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CreateLessonPlanRequest,
    CreateProgressNoteRequest,
    LessonPlanList,
    LessonPlanView,
    ProgressNoteList,
    ProgressNoteView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_lead_surface, require_coach_surface

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
    rows = await use_cases.list_progress_notes.execute(claims.user_id, session_id)
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
        )
    )
    return ProgressNoteView(**row.model_dump())
