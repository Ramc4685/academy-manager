"""Public parent magic-link consume route.

POST-only by design: e-mail security scanners and link-preview bots issue GET
prefetches, and a one-time token must never be burned by a bot before the parent
clicks. The token is read from the JSON body, never the query string, so it does
not leak into access logs or ``Referer`` headers.

Error mapping is handled by the shared ``DomainError`` exception handler:
``MagicLinkExpired`` → 410, ``MagicLinkInvalid`` → 401 (both raised by
``ConsumeMagicLink``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.identity.application.use_cases.magic_link import (
    ConsumeMagicLink,
)

router = APIRouter(prefix="/magic-link", tags=["magic-link"])


class ConsumeMagicLinkRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class ConsumeMagicLinkResponse(BaseModel):
    custom_token: str
    next_path: str


@router.post("/consume", response_model=ConsumeMagicLinkResponse)
async def consume_magic_link(
    request: Request, body: ConsumeMagicLinkRequest
) -> ConsumeMagicLinkResponse:
    # Resolve the tenant the same way public registration does: the middleware
    # already computed it from the request host and stored it on request.state.
    # In SaaS mode an unresolved tenant is a client error — never fall back to a
    # default academy, or the token's tenant binding is meaningless.
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    saas_mode = bool(getattr(request.app.state, "saas_mode", False))
    if saas_mode and not resolved_academy_id:
        raise HTTPException(
            status_code=400,
            detail="Tenant could not be resolved from the request host",
        )

    use_case: ConsumeMagicLink = request.app.state.consume_magic_link
    result = await use_case.execute(body.token, academy_id=resolved_academy_id or "")
    return ConsumeMagicLinkResponse(custom_token=result.custom_token, next_path=result.next_path)
