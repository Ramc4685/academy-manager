"""Public registration routes.

These endpoints are intentionally narrow. They accept a valid Firebase token
but do not require a pre-existing Mongo authorization row, because they create
that row for first-time parent onboarding.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.v2.contexts.identity.application.errors import (
    InvalidToken,
    LoginInviteSendFailed,
    VerificationEmailThrottled,
)
from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.contexts.identity.application.use_cases.send_registration_verification_email import (
    SendRegistrationVerificationEmail,
)
from backend.v2.shared.auth.claims import Role

log = logging.getLogger(__name__)

router = APIRouter(prefix="/register", tags=["registration"])

#: Returned verbatim for any send failure. The caller here is unauthenticated
#: apart from a self-minted Firebase token, so the underlying Firebase/Mongo
#: exception text — which can name collections, hosts and provider error codes —
#: must not travel back to them. The detail is logged instead.
_SEND_FAILED_DETAIL = "Could not send the verification email. Please try again shortly."

#: Same reasoning for the 401. ``InvalidToken`` wraps whatever the verifier
#: raised, which for a transport failure is the raw exception text — e.g. a
#: ``Max retries exceeded`` string naming internal hosts. The caller learns only
#: that the token was not accepted; the cause is logged.
_INVALID_TOKEN_DETAIL = "Not authenticated"


class RegisterParentResponse(BaseModel):
    user_id: str
    email: str
    academy_id: str
    roles: tuple[Role, ...]


@router.post("/parent", response_model=RegisterParentResponse)
async def register_parent(request: Request) -> RegisterParentResponse:
    token = _extract_bearer(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Resolve the tenant the parent is registering against. The middleware
    # already computed this from the request host (subdomain / custom
    # domain / approved internal header) and stored it on request.state.
    # In SaaS mode an unresolved tenant is a client error (400) — we
    # MUST NOT fall back to ``default-academy`` here (fixes #81).
    resolved_academy_id = _resolve_academy_id(request)

    use_case: RegisterPublicParent = request.app.state.register_public_parent
    user = await use_case.execute(token, academy_id=resolved_academy_id)
    return RegisterParentResponse(
        user_id=user.user_id,
        email=user.email,
        academy_id=user.academy_id,
        roles=user.roles,
    )


@router.post("/parent/verification-email", status_code=204)
async def send_parent_verification_email(request: Request) -> None:
    """Send the branded, our-domain verification email for a just-created
    parent account, instead of relying on Firebase's unbranded default
    mailer (which was confirmed landing in spam)."""
    token = _extract_bearer(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    resolved_academy_id = _resolve_academy_id(request)

    academy_id = resolved_academy_id or str(
        getattr(request.app.state, "default_academy_id", "") or ""
    )

    use_case: SendRegistrationVerificationEmail = (
        request.app.state.send_registration_verification_email
    )
    try:
        await use_case.execute(token, academy_id=academy_id)
    except InvalidToken as exc:
        log.warning("verification email token rejected: %s", exc, exc_info=True)
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN_DETAIL) from exc
    except VerificationEmailThrottled as exc:
        # The message is deliberately safe to show: it says only that a mail was
        # sent recently to the address the caller already supplied, so it leaks
        # nothing they did not bring with them.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LoginInviteSendFailed as exc:
        log.error("verification email send failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=_SEND_FAILED_DETAIL) from exc


def _resolve_academy_id(request: Request) -> str | None:
    # Same tenant-resolution contract as /register/parent (see fixes #81
    # comment on RegisterPublicParent): the middleware resolves the tenant
    # from the request host; SaaS mode must not fall back to a default.
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    saas_mode = bool(getattr(request.app.state, "saas_mode", False))
    if saas_mode and not resolved_academy_id:
        raise HTTPException(
            status_code=400,
            detail="Tenant could not be resolved from the request host",
        )
    return resolved_academy_id


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
