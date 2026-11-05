"""Coach routes for the text-only technique observation draft (B6 part 2).

``GET /ai/status`` tells the coach shell whether a model is wired at all (the
admin status route is a different persona, so a coach-only user cannot read
it). The draft route has the same student-coverage guard as the skill-note
routes; the draft is returned, never stored: the coach approves it by saving
it through the existing ``POST /students/{student_id}/skill-notes``.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.skill_routes import _require_assigned_to_student
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_surface

router = APIRouter(tags=["coach-ai-technique"])


class _DraftForStudent(Protocol):
    async def execute(self, *, student_id: str, observation: str, approver: str) -> object: ...


class TechniqueObservationBody(BaseModel):
    observation: str = Field(min_length=1, max_length=500)


def _draft(request: Request) -> _DraftForStudent:
    return request.app.state.ai_technique.draft_for_student  # type: ignore[no-any-return]


@router.get("/ai/status")
async def ai_status(
    request: Request,
    _claims: AuthClaims = Depends(require_coach_surface()),
) -> dict[str, bool]:
    return {"enabled": bool(request.app.state.ai_technique.enabled)}


@router.post("/students/{student_id}/technique-observation-draft")
async def draft_technique_observation(
    student_id: str,
    body: TechniqueObservationBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
    draft: _DraftForStudent = Depends(_draft),
) -> object:
    await _require_assigned_to_student(use_cases, claims.user_id, student_id)
    result = await draft.execute(
        student_id=student_id, observation=body.observation, approver=claims.user_id
    )
    return result.model_dump() if hasattr(result, "model_dump") else result
