"""Platform-admin AI usage meter per academy (plan 2026-11-04 Phase 2, A3).

``GET /api/v2/platform/academies/{academy_id}/ai-usage``: the same meter the
academy admin sees, for the academy named on the path. Unknown academy and
wrong persona are both 404, like the application-fee route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.v2.interfaces.admin.ai_usage_routes import AiUsageView
from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform", tags=["platform-ai-usage"])


def get_ai_usage_wiring(request: Request) -> Any:
    wiring = getattr(request.app.state, "ai_usage", None)
    if wiring is None:
        raise HTTPException(status_code=503, detail="AI usage is not configured")
    return wiring


@router.get(
    "/academies/{academy_id}/ai-usage",
    response_model=AiUsageView,
    summary="Read an academy's AI usage this month",
)
async def get_academy_ai_usage(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    wiring: Any = Depends(get_ai_usage_wiring),
) -> AiUsageView:
    usage = await wiring.get_ai_usage_for_academy.execute(academy_id)
    return AiUsageView(**usage.model_dump())
