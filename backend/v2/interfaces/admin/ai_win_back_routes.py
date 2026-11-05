"""Owner-only switch for AI-personalised win-back wording (B6 part 1).

Turning it on is the owner's standing approval of the drafted paragraph:
the daily job sends it without per-message review, so both routes are
``require_owner`` and listed in ``owner_gate.OWNER_ONLY_ROUTE_PATHS``.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

router = APIRouter(tags=["admin.ai-win-back"])


class _Setting(Protocol):
    async def get(self) -> tuple[bool, str | None]: ...
    async def set(self, *, enabled: bool, user_id: str) -> bool: ...


class AiWinBackPersonalisedView(BaseModel):
    enabled: bool


class AiWinBackPersonalisedRequest(BaseModel):
    enabled: bool


def _setting(request: Request) -> _Setting:
    return request.app.state.ai_win_back.setting  # type: ignore[no-any-return]


@router.get("/ai/win-back-personalised", response_model=AiWinBackPersonalisedView)
async def get_win_back_personalised(
    _claims: AuthClaims = Depends(require_owner()),
    setting: _Setting = Depends(_setting),
) -> AiWinBackPersonalisedView:
    enabled, _by = await setting.get()
    return AiWinBackPersonalisedView(enabled=enabled)


@router.put("/ai/win-back-personalised", response_model=AiWinBackPersonalisedView)
async def put_win_back_personalised(
    body: AiWinBackPersonalisedRequest,
    claims: AuthClaims = Depends(require_owner()),
    setting: _Setting = Depends(_setting),
) -> AiWinBackPersonalisedView:
    enabled = await setting.set(enabled=body.enabled, user_id=claims.user_id)
    return AiWinBackPersonalisedView(enabled=enabled)
