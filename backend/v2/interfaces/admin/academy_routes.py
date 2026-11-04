"""Admin academy settings routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile

from backend.v2.contexts.identity.application.academy_media import (
    MAX_PHOTO_UPLOAD_BYTES,
    LogoRateLimited,
    LogoRejected,
    LogoTooLarge,
    MediaStorageUnavailable,
    too_large_message,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.owner_gate import (
    ensure_owner_for_currency_change,
    ensure_owner_for_timezone_change,
)
from backend.v2.interfaces.admin.views import (
    AdminAcademyMediaView,
    AdminAcademyView,
    AdminGatewayConnectLinkView,
    AdminGatewayView,
    AdminNotificationsView,
    UpdateAdminAcademyRequest,
    UpdateAdminNotificationsRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.http import require_owner, require_persona

router = APIRouter(tags=["admin.academy"])


async def _academy_frontend(use_cases: AdminUseCases, academy_id: str | None) -> str:
    """Base URL for a Stripe return link: the academy's own host (row 9).

    ``academy_id`` must already be authorised (claims or verified OAuth
    state); the request's Host is never consulted. Falls back to the
    deployment's ``frontend_url`` when unknown or not composed.
    """
    lookup = getattr(use_cases, "academy_frontend_base_url", None)
    if academy_id and lookup is not None:
        return str(await lookup(academy_id)).rstrip("/")
    return (get_settings().frontend_url or "").rstrip("/")


# --- Academy profile ---


@router.get("/academy", response_model=AdminAcademyView)
async def get_academy_settings(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAcademyView:
    out = await use_cases.get_academy_use_case.execute(claims.academy_id)
    return AdminAcademyView(**asdict(out), invoice_prefix=await _invoice_prefix(use_cases))


@router.patch("/academy", response_model=AdminAcademyView)
async def update_academy_settings(
    payload: UpdateAdminAcademyRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAcademyView:
    changes = payload.model_dump(exclude_unset=True)
    previous_timezone: str | None = None
    timezone_changes = False
    if "timezone" in changes or "currency" in changes:
        # Money is owner-only (Settings overhaul Phase 1 PR 5). Timezone and
        # currency are refused for a non-owner only when they actually change,
        # so resubmitting the stored values is not an error.
        current = await use_cases.get_academy_use_case.execute(claims.academy_id)
        previous_timezone = current.timezone
        if "timezone" in changes and _blank_to_none(changes["timezone"]) != _blank_to_none(
            current.timezone
        ):
            timezone_changes = True
            ensure_owner_for_timezone_change(claims)
        if "currency" in changes:
            if _upper(changes["currency"]) != _upper(current.currency):
                ensure_owner_for_currency_change(claims)
            else:
                # Equal ignoring case counts as unchanged, so keep the stored
                # spelling: an admin must not rewrite "USD" as "usd".
                changes.pop("currency")
    out = await use_cases.update_academy_use_case.execute(claims.academy_id, changes)
    if timezone_changes and use_cases.record_money_setting_change is not None:
        await use_cases.record_money_setting_change.execute(
            academy_id=claims.academy_id,
            action="academy_timezone_changed",
            actor_id=claims.user_id,
            before={"timezone": previous_timezone},
            # What was stored, not the use case's "UTC" display fallback.
            after={"timezone": _blank_to_none(changes["timezone"])},
            reason="Settings -> Academy",
        )
    return AdminAcademyView(**asdict(out), invoice_prefix=await _invoice_prefix(use_cases))


#: Room for multipart boundaries and headers around the largest file.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
#: The body is bounded before it is parsed, so before the ``purpose`` field
#: can be read: the streaming cap is the largest per-purpose limit (photos).
#: The use case then applies the purpose's own limit (a logo stays 2 MB).
_MAX_BODY_BYTES = MAX_PHOTO_UPLOAD_BYTES + _MULTIPART_OVERHEAD_BYTES
_CONSENT_TRUE = frozenset({"true", "1", "on", "yes"})


@router.post(
    "/academy/media",
    response_model=AdminAcademyMediaView,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "purpose": {
                                "type": "string",
                                "enum": ["logo", "hero", "gallery", "coach"],
                                "default": "logo",
                            },
                            "consent": {"type": "boolean", "default": False},
                        },
                    }
                }
            },
        }
    },
)
async def upload_academy_media(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAcademyMediaView:
    """Upload an academy image (PNG or JPEG); returns its URL.

    Optional multipart ``purpose``: ``logo`` (default; up to 2 MB, 512 px),
    or a landing-page photo, ``hero`` / ``gallery`` (up to 5 MB, 2400 px long
    edge) or ``coach`` (up to 5 MB, 800 px). A ``gallery`` upload needs
    ``consent=true`` (parents or guardians of anyone shown agreed) or it is a
    422. Owner and admins may upload.

    The academy is the caller's resolved tenant, never a request field. The
    URL is saved by the caller through ``PATCH /academy``. ``Content-Length``
    is a cheap early refusal; the body is also counted as it streams in and
    cut off past the limit before any parsing, and chunked framing is refused,
    so no header combination lets an unbounded body reach the parser.
    """
    uploader = use_cases.upload_academy_logo
    if uploader is None:
        raise HTTPException(
            status_code=503,
            detail="Logo upload is not set up yet. Paste a link to your logo instead.",
        )
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit():
        raise HTTPException(status_code=411, detail="Upload could not be read. Try again.")
    if int(declared) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=too_large_message(MAX_PHOTO_UPLOAD_BYTES),
        )
    if "transfer-encoding" in request.headers:
        # Content-Length alone bounds nothing once chunked framing is also
        # sent (h11 passes both through), so refuse it outright.
        raise HTTPException(status_code=411, detail="Upload could not be read. Try again.")
    limit = _MAX_BODY_BYTES
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            # Counted on the wire, whatever the headers claim.
            raise HTTPException(
                status_code=413,
                detail=too_large_message(MAX_PHOTO_UPLOAD_BYTES),
            )
    sent = False

    async def replay() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    try:
        form = await Request(request.scope, replay).form(max_files=1, max_fields=4)
    except Exception:
        raise HTTPException(status_code=422, detail="Choose an image file to upload.") from None
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=422, detail="Choose an image file to upload.")
        raw = await upload.read(MAX_PHOTO_UPLOAD_BYTES + 1)
        purpose_field = form.get("purpose")
        purpose = purpose_field.strip().lower() if isinstance(purpose_field, str) else "logo"
        consent_field = form.get("consent")
        consent = isinstance(consent_field, str) and consent_field.strip().lower() in _CONSENT_TRUE
    finally:
        await form.close()
    try:
        result = await uploader.execute(
            academy_id=claims.academy_id,
            uploaded_by=claims.user_id,
            raw=raw,
            purpose=purpose or "logo",
            consent=consent,
        )
    except LogoTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except LogoRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except LogoRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except MediaStorageUnavailable:
        raise HTTPException(
            status_code=502,
            detail="We could not save the image. Try again in a moment.",
        ) from None
    return AdminAcademyMediaView(
        logo_url=result.url if result.purpose == "logo" else None,
        url=result.url,
        purpose=result.purpose,
    )


def _blank_to_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _upper(value: object) -> str | None:
    text = _blank_to_none(value)
    return text.upper() if text else None


async def _invoice_prefix(use_cases: AdminUseCases) -> str | None:
    """The academy's platform-set invoice prefix, shown read-only in Settings."""
    reader = getattr(use_cases, "get_invoice_prefix", None)
    if reader is None:
        return None
    prefix: str | None = await reader.execute()
    return prefix


# `GET`/`PATCH /academy/fees` (the legacy Settings -> Data-era fees routes)
# were retired in the Settings overhaul (Lane D, PR 7): nothing calls them —
# the frontend has no caller left, and the Billing rules panel writes through
# `POST /admin/billing/rules` instead (`billing_rules_routes.py`), which
# reuses `get_academy_fees_use_case` / `update_academy_fees_use_case`
# directly. Those use cases stay; only the HTTP routes are gone.


@router.get("/academy/gateway", response_model=AdminGatewayView)
async def get_academy_gateway(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGatewayView:
    out = await use_cases.get_academy_gateway_use_case.execute(claims.academy_id)
    return AdminGatewayView(**asdict(out))


@router.post("/academy/gateway/stripe/connect-link", response_model=AdminGatewayConnectLinkView)
async def start_stripe_connect(
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGatewayConnectLinkView:
    if use_cases.start_connect_onboarding_use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Online payouts are not set up yet. Finish payment setup in academy settings.",
        )
    frontend = await _academy_frontend(use_cases, claims.academy_id)
    result = await use_cases.start_connect_onboarding_use_case.start(
        academy_id=claims.academy_id,
        refresh_url=f"{frontend}/admin/settings?panel=gateway&stripe=error",
        return_url=f"{frontend}/admin/settings?panel=gateway&stripe=connected",
    )
    return AdminGatewayConnectLinkView(url=result["onboarding_url"])


@router.get("/academy/gateway/stripe/callback")
async def stripe_connect_callback(
    code: str = Query(),
    state: str = Query(),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> RedirectResponse:
    settings = get_settings()
    frontend = settings.frontend_url or ""
    if use_cases.complete_stripe_connect_use_case is None:
        return RedirectResponse(
            url=f"{frontend}/admin/settings?panel=gateway&stripe=error",
            status_code=302,
        )
    try:
        academy_id = await use_cases.complete_stripe_connect_use_case.execute(
            code=code, state=state
        )
    except ValueError:
        return RedirectResponse(
            url=f"{frontend}/admin/settings?panel=gateway&stripe=error",
            status_code=302,
        )
    # ``academy_id`` comes from the HMAC-verified ``state``, so the redirect
    # host is the academy's own, never anything the caller controls.
    frontend = await _academy_frontend(use_cases, academy_id)
    return RedirectResponse(
        url=f"{frontend}/admin/settings?panel=gateway&stripe=connected",
        status_code=302,
    )


@router.delete("/academy/gateway/stripe/connect", status_code=204)
async def disconnect_stripe(
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    if use_cases.disconnect_stripe_use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Online payouts are not set up yet. Finish payment setup in academy settings.",
        )
    await use_cases.disconnect_stripe_use_case.execute(claims.academy_id)


# --- Notifications ---


@router.get("/academy/notifications", response_model=AdminNotificationsView)
async def get_academy_notifications(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminNotificationsView:
    out = await use_cases.get_academy_notifications_use_case.execute(claims.academy_id)
    return AdminNotificationsView(**asdict(out))


@router.patch("/academy/notifications", response_model=AdminNotificationsView)
async def update_academy_notifications(
    payload: UpdateAdminNotificationsRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminNotificationsView:
    out = await use_cases.update_academy_notifications_use_case.execute(
        claims.academy_id, payload.model_dump(exclude_unset=True)
    )
    return AdminNotificationsView(**asdict(out))
