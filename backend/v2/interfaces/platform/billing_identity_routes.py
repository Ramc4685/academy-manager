"""Platform-admin billing identity per academy (Settings overhaul Phase 1 PR 2).

``GET/PUT /api/v2/platform/academies/{academy_id}/billing-identity``. Today
this is the academy's invoice-number prefix (``BLNO`` -> ``BLNO-2026-09-0042``):
derived from the slug when the academy is created, changeable here by a
platform admin until the academy's first numbered invoice (then 409), unique
across academies (409), audited on every change. Tenant admins see it
read-only in Settings and have no route to change it. Wrong-persona access is
404 (``require_platform_admin``), like every platform route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.invoice_prefix import (
    InvoicePrefixResult,
    SetInvoicePrefixCommand,
)
from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform", tags=["platform-billing-identity"])


class BillingIdentityResponse(BaseModel):
    academy_id: str
    invoice_prefix: str | None
    #: True once the academy has a numbered invoice; the prefix can no longer change.
    locked: bool


class SetBillingIdentityRequest(BaseModel):
    # Format (2-6 of A-Z/0-9, letter first) is checked by the use case, which
    # also uppercases; a bad value is a 422 either way.
    invoice_prefix: str = Field(min_length=1, max_length=32)
    reason: str | None = Field(default=None, max_length=500)


def get_platform_billing_identity(request: Request) -> Any:
    wiring = getattr(request.app.state, "platform_billing_identity", None)
    if wiring is None:
        raise HTTPException(status_code=503, detail="Billing identity is not configured")
    return wiring


def _response(result: InvoicePrefixResult) -> BillingIdentityResponse:
    return BillingIdentityResponse(**result.model_dump())


@router.get(
    "/academies/{academy_id}/billing-identity",
    response_model=BillingIdentityResponse,
    summary="Read an academy's invoice prefix and whether it is locked",
)
async def get_billing_identity(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    wiring: Any = Depends(get_platform_billing_identity),
) -> BillingIdentityResponse:
    return _response(await wiring.get.execute(academy_id))


@router.put(
    "/academies/{academy_id}/billing-identity",
    response_model=BillingIdentityResponse,
    summary="Set an academy's invoice prefix (refused after its first numbered invoice)",
)
async def set_billing_identity(
    academy_id: str,
    payload: SetBillingIdentityRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    wiring: Any = Depends(get_platform_billing_identity),
) -> BillingIdentityResponse:
    result = await wiring.set.execute(
        SetInvoicePrefixCommand(
            academy_id=academy_id,
            invoice_prefix=payload.invoice_prefix,
            actor_id=claims.user_id,
            reason=payload.reason,
        )
    )
    return _response(result)
