"""Public token-authenticated unsubscribe routes (#555).

POST-only, for the reason ``magic_link_routes`` already documents: e-mail
security scanners and link-preview bots issue GET prefetches, so a GET that
mutated preferences would let a corporate mail scanner unsubscribe families
automatically. The emailed link points at a frontend page carrying the token in
the query string; the mutation is a POST from that page.

The token is the entire authority — no login — so two things are non-negotiable
here:

* it is verified against the tenant the request resolved to, so one recipient's
  token can never flip another academy's rows;
* every failure is the same opaque 401 with no detail, so the endpoint cannot
  be used to probe which recipients exist.

``transactional`` is not a field these routes accept. A request that sends one
is rejected rather than ignored, so nobody can believe they switched off their
invoices.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.communications.application.use_cases.resolve_unsubscribe_token import (
    ResolveUnsubscribeToken,
    UnsubscribeTokenInvalid,
)
from backend.v2.contexts.communications.application.use_cases.set_email_preferences import (
    SetEmailPreferences,
    SetEmailPreferencesCommand,
)
from backend.v2.shared.tenancy import tenant_scope

router = APIRouter(prefix="/unsubscribe", tags=["unsubscribe"])

_INVALID_TOKEN_DETAIL = "This unsubscribe link is not valid."


class _TokenBody(BaseModel):
    # Reject unknown keys so a client that thinks it can pass
    # ``transactional`` gets a 422 instead of silent success.
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=1024)


class UnsubscribePreviewRequest(_TokenBody):
    pass


class UnsubscribeConfirmRequest(_TokenBody):
    campaigns: bool
    digests: bool


class UnsubscribeStateResponse(BaseModel):
    campaigns_opted_out: bool
    digests_opted_out: bool


def _resolver(request: Request) -> ResolveUnsubscribeToken:
    use_case: ResolveUnsubscribeToken | None = getattr(
        request.app.state, "resolve_unsubscribe_token", None
    )
    if use_case is None or use_case.secret is None:
        # Fail closed: with no signing secret there is no such thing as a valid
        # token, and no link was ever rendered. 404 rather than 401 so the
        # surface simply does not exist.
        raise HTTPException(status_code=404, detail="Unsubscribe is not configured.")
    return use_case


def _resolve(request: Request, token: str) -> tuple[str, str]:
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    try:
        target = _resolver(request).execute(token, expected_academy_id=resolved_academy_id)
    except UnsubscribeTokenInvalid:
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN_DETAIL) from None
    return target.academy_id, target.user_id


@router.post("/preview", response_model=UnsubscribeStateResponse)
async def preview_unsubscribe(
    request: Request, body: UnsubscribePreviewRequest
) -> UnsubscribeStateResponse:
    academy_id, user_id = _resolve(request, body.token)
    get_preferences = request.app.state.get_email_preferences
    with tenant_scope(academy_id):
        current = await get_preferences.execute(user_id)
    return UnsubscribeStateResponse(
        campaigns_opted_out=current.campaigns_opted_out,
        digests_opted_out=current.digests_opted_out,
    )


@router.post("/confirm", response_model=UnsubscribeStateResponse)
async def confirm_unsubscribe(
    request: Request, body: UnsubscribeConfirmRequest
) -> UnsubscribeStateResponse:
    academy_id, user_id = _resolve(request, body.token)
    set_preferences: SetEmailPreferences = request.app.state.set_email_preferences
    with tenant_scope(academy_id):
        saved = await set_preferences.execute(
            SetEmailPreferencesCommand(
                user_id=user_id,
                campaigns_opted_out=body.campaigns,
                digests_opted_out=body.digests,
                source="link",
            )
        )
    return UnsubscribeStateResponse(
        campaigns_opted_out=saved.campaigns_opted_out,
        digests_opted_out=saved.digests_opted_out,
    )
