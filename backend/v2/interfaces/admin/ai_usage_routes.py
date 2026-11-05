"""Admin AI usage meter: ``GET /api/v2/admin/ai/usage`` (plan 2026-11-04
Phase 2, slice A3). Read-only; the cap shown here is a soft prompt."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.ai"])


class AiUsageView(BaseModel):
    used: int
    cap: int
    tier: Literal["free", "growth"]
    upgrade_suggested: bool
    month: str


def get_ai_usage_wiring(request: Request) -> Any:
    wiring = getattr(request.app.state, "ai_usage", None)
    if wiring is None:
        raise HTTPException(status_code=503, detail="AI usage is not configured")
    return wiring


@router.get("/ai/usage", response_model=AiUsageView)
async def get_ai_usage(
    _claims: AuthClaims = Depends(require_persona("admin")),
    wiring: Any = Depends(get_ai_usage_wiring),
) -> AiUsageView:
    usage = await wiring.get_ai_usage.execute()
    return AiUsageView(**usage.model_dump())
