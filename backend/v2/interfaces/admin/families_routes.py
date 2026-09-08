"""Admin BFF: the Family billing page.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3, §5.

Services are attached at ``app.state.admin_families`` by
``composition/families.py`` (``composition/admin.py`` is at its line budget).
This module only knows their protocols. Owner-only actions are stripped here
for non-owner callers so the page never renders a button the backend refuses;
the write routes themselves keep their own ``require_owner`` guards.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.v2.contexts.billing.application.family_billing import (
    FamilyBillingUnavailable,
    strip_owner_actions,
)
from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopayResult,
)
from backend.v2.interfaces.admin.families_views import (
    AdminFamilyBillingView,
    PauseFamilyAutopayRequest,
    PauseFamilyAutopayResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


class FamilyBillingReader(Protocol):
    async def build(self, parent_id: str) -> dict[str, Any] | None: ...


class FamilyAutopayPauser(Protocol):
    async def execute(
        self, *, academy_id: str, parent_id: str, actor_id: str, reason: str, request_id: str
    ) -> PauseFamilyAutopayResult: ...


class AdminFamiliesServices(Protocol):
    reader: FamilyBillingReader
    pause_autopay: FamilyAutopayPauser


def get_admin_families(request: Request) -> AdminFamiliesServices:
    services: AdminFamiliesServices = request.app.state.admin_families
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


router = APIRouter(tags=["admin.families"])


@router.get("/families/{parent_id}/billing", response_model=AdminFamilyBillingView)
async def family_billing(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> AdminFamilyBillingView:
    """One parent's billing picture: header, students, invoices, timeline, actions."""
    try:
        view = await services.reader.build(parent_id)
    except FamilyBillingUnavailable as exc:
        raise HTTPException(status_code=503, detail="family billing unavailable") from exc
    if view is None:
        raise HTTPException(status_code=404, detail="family not found")
    if "owner" not in claims.roles:
        view = strip_owner_actions(view)
    return AdminFamilyBillingView.model_validate(view)


@router.post("/families/{parent_id}/autopay/pause", response_model=PauseFamilyAutopayResponse)
async def pause_family_autopay(
    parent_id: str,
    body: PauseFamilyAutopayRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> PauseFamilyAutopayResponse:
    """Autopay OFF for the whole family: every active enrollment becomes ``paused``."""
    try:
        result = await services.pause_autopay.execute(
            academy_id=_academy_id(claims),
            parent_id=parent_id,
            actor_id=claims.user_id,
            reason=body.reason,
            request_id=body.request_id,
        )
    except NothingToPause as exc:
        raise HTTPException(status_code=400, detail=str(exc).split(":", 1)[0]) from exc
    return PauseFamilyAutopayResponse(
        paused_count=result.paused_count,
        active_count_before=result.active_count_before,
        warnings=list(result.warnings),
    )
