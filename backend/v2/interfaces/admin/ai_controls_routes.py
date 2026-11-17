"""Owner-only AI limits: the monthly call cap, per-feature daily ceilings and
whether coaches review AI progress notes before parents see them (L13).

``GET``/``PUT /admin/ai/controls``. Turning coach review off sends AI text to
parents unread, so both routes are ``require_owner`` and listed in
``owner_gate.OWNER_ONLY_ROUTE_PATHS``; every change is audited as
``ai_controls.changed`` (``composition/ai.py::AcademyAiControls``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.composition.ai import CAPPABLE_FEATURES, AiControls
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

router = APIRouter(tags=["admin.ai-controls"])

MAX_MONTHLY_CALL_CAP = 5000
MAX_DAILY_CALL_CAP = 1000


class AiControlsView(BaseModel):
    monthly_call_cap: int
    daily_call_caps: dict[str, int]
    coach_review_narratives: bool
    #: Features a daily ceiling can be set for, in display order.
    features: list[str]


class AiControlsRequest(BaseModel):
    monthly_call_cap: int = Field(ge=0, le=MAX_MONTHLY_CALL_CAP)
    #: Required: the PUT replaces every ceiling, so omitting it must not wipe them.
    daily_call_caps: dict[str, Annotated[int, Field(ge=0, le=MAX_DAILY_CALL_CAP)]]
    coach_review_narratives: bool


def _controls(request: Request) -> Any:
    return request.app.state.ai.controls


def _view(controls: AiControls) -> AiControlsView:
    return AiControlsView(
        monthly_call_cap=controls.monthly_call_cap,
        daily_call_caps=controls.daily_call_caps,
        coach_review_narratives=controls.coach_review_narratives,
        features=list(CAPPABLE_FEATURES),
    )


@router.get("/ai/controls", response_model=AiControlsView)
async def get_ai_controls(
    _claims: AuthClaims = Depends(require_owner()),
    controls: Any = Depends(_controls),
) -> AiControlsView:
    return _view(await controls.get())


@router.put("/ai/controls", response_model=AiControlsView)
async def put_ai_controls(
    body: AiControlsRequest,
    claims: AuthClaims = Depends(require_owner()),
    controls: Any = Depends(_controls),
) -> AiControlsView:
    unknown = sorted(set(body.daily_call_caps) - set(CAPPABLE_FEATURES))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown AI features: {', '.join(unknown)}.")
    saved = await controls.set(
        AiControls(
            monthly_call_cap=body.monthly_call_cap,
            daily_call_caps=dict(body.daily_call_caps),
            coach_review_narratives=body.coach_review_narratives,
        ),
        user_id=claims.user_id,
    )
    return _view(saved)
