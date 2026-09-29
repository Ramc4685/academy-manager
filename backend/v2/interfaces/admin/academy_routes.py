"""Admin academy settings routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.owner_gate import (
    ensure_owner_for_currency_change,
    ensure_owner_for_timezone_change,
)
from backend.v2.interfaces.admin.views import (
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
