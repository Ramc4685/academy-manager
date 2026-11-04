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

``/unsubscribe/prospect`` is the lead-facing variant for a ``crm_contact:``
recipient (a website inquiry, never a user): a backend-rendered page, because
prospects have no portal and no frontend route exists for them. Same token
scheme, same tenant binding, same opaque failure; GET only renders the form,
POST records the opt-out by address (``composition/prospect_email.py``).
"""

from __future__ import annotations

import html
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.communications.application.prospect_recipient import (
    prospect_contact_id,
)
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
    # Optional, and optional on purpose (#612). The model forbids extra keys,
    # so a required field here would 422 every request from the currently
    # deployed unsubscribe page; a `= False` default would silently
    # re-subscribe anyone who saved from it. `None` means "leave unchanged".
    notifications: bool | None = None


class UnsubscribeStateResponse(BaseModel):
    campaigns_opted_out: bool
    digests_opted_out: bool
    notifications_opted_out: bool = False


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
    # Same contract as ``magic_link_routes``: in SaaS mode an unresolved tenant
    # is a client error, never a pass. The middleware computes this from the
    # request host, and the emailed link is built on the academy's own
    # subdomain (``UnsubscribeLinkBuilder``), so a request that cannot be
    # resolved did not come from a link we minted. Accepting it would make the
    # ``expected_academy_id`` binding below a no-op on the exact host the
    # emailed link uses — the branch would exist but never run.
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    if bool(getattr(request.app.state, "saas_mode", False)) and not resolved_academy_id:
        raise HTTPException(
            status_code=400,
            detail="Tenant could not be resolved from the request host",
        )
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
        notifications_opted_out=current.notifications_opted_out,
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
                notifications_opted_out=body.notifications,
                source="link",
            )
        )
    return UnsubscribeStateResponse(
        campaigns_opted_out=saved.campaigns_opted_out,
        digests_opted_out=saved.digests_opted_out,
        notifications_opted_out=saved.notifications_opted_out,
    )


# --- prospect (lead) unsubscribe: backend-rendered ---------------------------

_PAGE_STYLE = (
    "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;"
    "margin:48px auto;padding:0 20px;color:#0f172a;line-height:1.5;"
)
_BUTTON_STYLE = (
    "background:#1d4ed8;color:#fff;border:0;border-radius:6px;padding:10px 18px;"
    "font-size:15px;cursor:pointer;"
)


def _page(status: int, title: str, body_html: str) -> HTMLResponse:
    content = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(title)}</title></head>"
        f'<body style="{_PAGE_STYLE}"><h1 style="font-size:22px;">{html.escape(title)}</h1>'
        f"{body_html}</body></html>"
    )
    return HTMLResponse(content, status_code=status, headers={"Cache-Control": "no-store"})


def _invalid_page() -> HTMLResponse:
    # A fresh response per request: middleware stamps headers on the instance.
    return _page(
        401, "This link is not valid", "<p>Ask the academy to stop emailing you instead.</p>"
    )


def _prospect_target(request: Request, token: str) -> tuple[str, str] | None:
    """``(academy_id, recipient_id)`` for a prospect token, else ``None``."""
    try:
        academy_id, user_id = _resolve(request, token)
    except HTTPException:
        return None
    if prospect_contact_id(user_id) is None:
        return None
    return academy_id, user_id


_TOKEN_QUERY = Query(alias="t", min_length=1, max_length=1024)


@router.get("/prospect", response_class=HTMLResponse, include_in_schema=False)
async def prospect_unsubscribe_page(request: Request, token: str = _TOKEN_QUERY) -> HTMLResponse:
    """The emailed link lands here. Renders the form; mutates nothing."""
    if _prospect_target(request, token) is None:
        return _invalid_page()
    return _page(
        200,
        "Stop emails about your inquiry?",
        "<p>You asked this academy about a class. Confirm below and it will not "
        "email you about that inquiry again.</p>"
        f'<form method="post" action="?t={html.escape(quote(token, safe=""), quote=True)}">'
        f'<button type="submit" style="{_BUTTON_STYLE}">Stop these emails</button></form>',
    )


@router.post("/prospect", response_class=HTMLResponse, include_in_schema=False)
async def prospect_unsubscribe_confirm(request: Request, token: str = _TOKEN_QUERY) -> HTMLResponse:
    target = _prospect_target(request, token)
    if target is None:
        return _invalid_page()
    academy_id, recipient_id = target
    done = await request.app.state.unsubscribe_prospect.execute(
        academy_id=academy_id, recipient_id=recipient_id
    )
    if not done:
        return _invalid_page()
    return _page(
        200,
        "Done",
        "<p>This academy will not email you about your inquiry again.</p>",
    )
