"""Public "forgot password" route.

Anonymous by necessity (the caller cannot sign in), so it always answers 204
whether or not the address is known: the response must not reveal which emails
have accounts. Abuse is bounded by the per-IP public-write rate limit and the
per-mailbox cooldown inside the use case.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.identity.application.use_cases.send_password_reset_email import (
    SendPasswordResetEmail,
)

router = APIRouter(prefix="/password-reset", tags=["password-reset"])


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("", status_code=204)
async def request_password_reset(request: Request, body: PasswordResetRequest) -> None:
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    saas_mode = bool(getattr(request.app.state, "saas_mode", False))
    if saas_mode and not resolved_academy_id:
        raise HTTPException(
            status_code=400,
            detail="Tenant could not be resolved from the request host",
        )
    academy_id = resolved_academy_id or str(
        getattr(request.app.state, "default_academy_id", "") or ""
    )
    use_case: SendPasswordResetEmail = request.app.state.send_password_reset_email
    await use_case.execute(body.email, academy_id=academy_id)
