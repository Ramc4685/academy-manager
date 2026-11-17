"""Admin BFF: the Month dates AI helper.

``POST /admin/schedule/suggest-no-class-dates`` with ``{text, class_dates}``
answers ``{no_class: [{date, reason}], notes, prompt_version}``. Writes only
the ``ai_calls`` row; the page pre-ticks the dates and the existing cancel
calls stay the approval gate. ``require_persona("admin")``.

AI off surfaces as 503 ``Ai.Disabled``, the cap as 429, an unreadable answer
as 502 ``Ai.ProviderError`` (shared error handler); the page then falls back
to reading plain dates itself.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.ai.application.use_cases.suggest_no_class_dates import (
    MAX_DATES,
    MAX_TEXT_CHARS,
    NoClassDraft,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.schedule"])


def get_ai_schedule(request: Request) -> Any:
    service = getattr(request.app.state, "ai_schedule", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AI date help is not configured")
    return service


class SuggestNoClassDatesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    class_dates: list[date] = Field(min_length=1, max_length=MAX_DATES)


class SuggestNoClassDatesResponse(NoClassDraft):
    prompt_version: str


@router.post("/schedule/suggest-no-class-dates", response_model=SuggestNoClassDatesResponse)
async def suggest_no_class_dates(
    body: SuggestNoClassDatesBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    service: Any = Depends(get_ai_schedule),
) -> SuggestNoClassDatesResponse:
    result = await service.execute(
        text=body.text, class_dates=body.class_dates, approver=claims.user_id
    )
    return SuggestNoClassDatesResponse(
        **result.draft.model_dump(), prompt_version=result.prompt_version
    )
