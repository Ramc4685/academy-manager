"""Admin academy settings routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminAcademyView,
    AdminFeesView,
    AdminNotificationsView,
    UpdateAdminAcademyRequest,
    UpdateAdminFeesRequest,
    UpdateAdminNotificationsRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
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
