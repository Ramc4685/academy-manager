"""GET/PUT /api/v2/parent/email-preferences — the logged-in half of #555.

The emailed one-click link (``interfaces/unsubscribe_routes.py``) is the
CAN-SPAM requirement; this is the same switch for a parent who is already
signed in, so a family that deleted the email is not stuck.

The request model has no ``transactional`` field, and forbids unknown keys, so
invoices and dunning notices cannot be switched off from here either.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.communications.application.use_cases.set_email_preferences import (
    SetEmailPreferencesCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.email-preferences"])


class EmailPreferencesResponse(BaseModel):
    campaigns_opted_out: bool
    digests_opted_out: bool


class UpdateEmailPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaigns_opted_out: bool
    digests_opted_out: bool


@router.get(
    "/email-preferences",
    response_model=EmailPreferencesResponse,
    summary="Get the current parent's email opt-out flags",
)
async def get_email_preferences(
    request: Request,
    claims: AuthClaims = Depends(require_persona("parent")),
) -> EmailPreferencesResponse:
    current = await request.app.state.get_email_preferences.execute(claims.user_id)
    return EmailPreferencesResponse(
        campaigns_opted_out=current.campaigns_opted_out,
        digests_opted_out=current.digests_opted_out,
    )


@router.put(
    "/email-preferences",
    response_model=EmailPreferencesResponse,
    summary="Set the current parent's email opt-out flags",
)
async def set_email_preferences(
    request: Request,
    body: UpdateEmailPreferencesRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
) -> EmailPreferencesResponse:
    saved = await request.app.state.set_email_preferences.execute(
        SetEmailPreferencesCommand(
            user_id=claims.user_id,
            campaigns_opted_out=body.campaigns_opted_out,
            digests_opted_out=body.digests_opted_out,
            email=getattr(claims, "email", None),
            source="portal",
        )
    )
    return EmailPreferencesResponse(
        campaigns_opted_out=saved.campaigns_opted_out,
        digests_opted_out=saved.digests_opted_out,
    )
