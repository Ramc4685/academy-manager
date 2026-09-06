"""Coach session feedback routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.v2.contexts.coaching.application.use_cases.session_feedback import (
    CreateFeedbackCommand,
)
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CreateFeedbackRequest,
    FeedbackListResponse,
    FeedbackView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_lead_surface

router = APIRouter(tags=["coach.feedback"])

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="session not assigned to coach"
)


async def _require_assigned(use_cases: CoachUseCases, coach_id: str, session_id: str) -> None:
    if not await use_cases.assigned_sessions.is_coach_assigned(coach_id, session_id):
        raise _FORBIDDEN


@router.post(
    "/sessions/{session_id}/feedback",
    response_model=FeedbackView,
    status_code=201,
)
async def create_feedback(
    session_id: str,
    body: CreateFeedbackRequest,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> FeedbackView:
    row = await use_cases.create_feedback.execute(
        CreateFeedbackCommand(
            session_id=session_id,
            occurrence_id=body.occurrence_id,
            student_id=body.student_id,
            body=body.body,
            rating=body.rating,
        ),
        coach_id=claims.user_id,
    )
    return FeedbackView(
        feedback_id=row.feedback_id,
        session_id=row.session_id,
        occurrence_id=row.occurrence_id,
        coach_id=row.coach_id,
        student_id=row.student_id,
        body=row.body,
        rating=row.rating,
        created_at=row.created_at,
    )


@router.get("/sessions/{session_id}/feedback", response_model=FeedbackListResponse)
async def list_feedback(
    session_id: str,
    claims: AuthClaims = Depends(require_coach_lead_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> FeedbackListResponse:
    await _require_assigned(use_cases, claims.user_id, session_id)
    rows = await use_cases.list_feedback.execute(session_id)
    return FeedbackListResponse(
        feedback=[
            FeedbackView(
                feedback_id=row.feedback_id,
                session_id=row.session_id,
                occurrence_id=row.occurrence_id,
                coach_id=row.coach_id,
                student_id=row.student_id,
                body=row.body,
                rating=row.rating,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )
