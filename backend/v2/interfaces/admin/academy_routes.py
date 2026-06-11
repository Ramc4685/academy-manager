"""Admin academy settings routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminAcademyView,
    AdminFeesView,
    AdminGatewayConnectLinkView,
    AdminGatewayView,
    AdminNotificationsView,
    UpdateAdminAcademyRequest,
    UpdateAdminFeesRequest,
    UpdateAdminNotificationsRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.academy"])


# --- Academy profile ---


@router.get("/academy", response_model=AdminAcademyView)
async def get_academy_settings(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAcademyView:
    out = await use_cases.get_academy_use_case.execute(claims.academy_id)
    return AdminAcademyView(**asdict(out))


@router.patch("/academy", response_model=AdminAcademyView)
async def update_academy_settings(
    payload: UpdateAdminAcademyRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAcademyView:
    out = await use_cases.update_academy_use_case.execute(
        claims.academy_id, payload.model_dump(exclude_unset=True)
    )
    return AdminAcademyView(**asdict(out))


# --- Fees ---


@router.get("/academy/fees", response_model=AdminFeesView)
async def get_academy_fees(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminFeesView:
    out = await use_cases.get_academy_fees_use_case.execute(claims.academy_id)
    return AdminFeesView(**asdict(out))


@router.get("/academy/gateway", response_model=AdminGatewayView)
async def get_academy_gateway(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGatewayView:
    out = await use_cases.get_academy_gateway_use_case.execute(claims.academy_id)
    return AdminGatewayView(**asdict(out))


@router.post("/academy/gateway/stripe/connect-link", response_model=AdminGatewayConnectLinkView)
async def start_stripe_connect(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGatewayConnectLinkView:
    assert use_cases.start_stripe_connect_use_case is not None
    out = await use_cases.start_stripe_connect_use_case.execute(claims.academy_id)
    return AdminGatewayConnectLinkView(url=out.url)


@router.get("/academy/gateway/stripe/callback")
async def stripe_connect_callback(
    code: str = Query(),
    state: str = Query(),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> RedirectResponse:
    settings = get_settings()
    frontend = settings.frontend_url or ""
    try:
        assert use_cases.complete_stripe_connect_use_case is not None
        await use_cases.complete_stripe_connect_use_case.execute(code=code, state=state)
    except (ValueError, AssertionError):
        return RedirectResponse(
            url=f"{frontend}/admin/settings?panel=gateway&stripe=error",
            status_code=302,
        )
    return RedirectResponse(
        url=f"{frontend}/admin/settings?panel=gateway&stripe=connected",
        status_code=302,
    )


@router.delete("/academy/gateway/stripe/connect", status_code=204)
async def disconnect_stripe(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    assert use_cases.disconnect_stripe_use_case is not None
    await use_cases.disconnect_stripe_use_case.execute(claims.academy_id)


@router.patch("/academy/fees", response_model=AdminFeesView)
async def update_academy_fees(
    payload: UpdateAdminFeesRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminFeesView:
    out = await use_cases.update_academy_fees_use_case.execute(
        claims.academy_id, payload.model_dump(exclude_unset=True)
    )
    return AdminFeesView(**asdict(out))


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
