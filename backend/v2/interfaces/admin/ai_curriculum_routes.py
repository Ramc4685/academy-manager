"""Admin BFF: AI drafting for the curriculum editor (B1 skill ladder).

* ``GET /admin/ai/status``: ``{enabled}``, false while the disabled model port
  is wired, so the frontend hides AI buttons.
* ``POST /admin/curriculum/programs/{program_id}/ladder-draft``: drafts
  levels, skills and criteria for the program's sport. Read-only on the
  database except for the ``ai_calls`` audit row; the owner saves the edited
  draft through the existing level/skill/criterion routes.

``require_persona("admin")`` throughout. ``AiDisabled`` (503 ``Ai.Disabled``),
``AiMonthlyCapReached`` (429) and ``AiProviderError`` (502) pass through the
shared domain-error handler untouched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.ai.application.use_cases.draft_skill_ladder import SkillLadderInput
from backend.v2.contexts.curriculum.application.errors import ProgramNotFound
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-ai-curriculum"])


def get_ai_curriculum(request: Request) -> Any:
    services = getattr(request.app.state, "ai_curriculum", None)
    if services is None:
        raise HTTPException(status_code=503, detail="AI drafting is not configured")
    return services


class LadderDraftBody(BaseModel):
    model_config = {"extra": "forbid"}

    age_band: str = Field(min_length=1, max_length=30)
    level_count: int = Field(default=4, ge=2, le=6)
    notes: str = Field(default="", max_length=500)


@router.get("/ai/status")
async def ai_status(
    _claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_ai_curriculum),
) -> dict[str, bool]:
    return {"enabled": bool(services.enabled)}


@router.post("/curriculum/programs/{program_id}/ladder-draft")
async def draft_skill_ladder(
    program_id: str,
    body: LadderDraftBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_ai_curriculum),
) -> dict[str, Any]:
    sport = await services.program_sport.sport_of(program_id)
    if sport is None:
        raise ProgramNotFound(f"program {program_id} not found")
    draft = await services.draft_skill_ladder.execute(
        SkillLadderInput(
            sport=sport.strip()[:60],
            age_band=body.age_band,
            level_count=body.level_count,
            notes=body.notes,
        ),
        approver=claims.user_id,
    )
    return {"prompt_version": services.draft_skill_ladder.prompt_version, **draft.model_dump()}
