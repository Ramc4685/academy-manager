"""Platform-admin application fee per academy (roadmap L9b).

``GET/PUT /api/v2/platform/academies/{academy_id}/application-fee``. The fee
is basis points of each destination charge routed to the academy's connected
account (Stripe ``application_fee_amount``), default 0. Only a platform admin
can read or change it: tenant admins have no route to it, and the academy-side
billing-settings write never persists the field. Wrong-persona access is 404
(``require_platform_admin``), like every platform route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    MAX_APPLICATION_FEE_BPS,
    ApplicationFeeResult,
    SetApplicationFeeCommand,
)
from backend.v2.interfaces.platform.bootstrap_routes import require_platform_admin
from backend.v2.shared.auth.claims import AuthClaims

router = APIRouter(prefix="/platform", tags=["platform-application-fee"])


class ApplicationFeeResponse(BaseModel):
    academy_id: str
    application_fee_bps: int
    max_application_fee_bps: int


class SetApplicationFeeRequest(BaseModel):
    application_fee_bps: int = Field(ge=0, le=MAX_APPLICATION_FEE_BPS)
    reason: str | None = Field(default=None, max_length=500)


def get_platform_application_fee(request: Request) -> Any:
    wiring = getattr(request.app.state, "platform_application_fee", None)
    if wiring is None:
        raise HTTPException(status_code=503, detail="Application fee is not configured")
    return wiring


def _response(result: ApplicationFeeResult) -> ApplicationFeeResponse:
    return ApplicationFeeResponse(**result.model_dump())


@router.get(
    "/academies/{academy_id}/application-fee",
    response_model=ApplicationFeeResponse,
    summary="Read an academy's platform application fee",
)
async def get_application_fee(
    academy_id: str,
    _: AuthClaims = Depends(require_platform_admin),
    wiring: Any = Depends(get_platform_application_fee),
) -> ApplicationFeeResponse:
    return _response(await wiring.get.execute(academy_id))


@router.put(
    "/academies/{academy_id}/application-fee",
    response_model=ApplicationFeeResponse,
    summary="Set an academy's platform application fee (basis points)",
)
async def set_application_fee(
    academy_id: str,
    payload: SetApplicationFeeRequest,
    claims: AuthClaims = Depends(require_platform_admin),
    wiring: Any = Depends(get_platform_application_fee),
) -> ApplicationFeeResponse:
    result = await wiring.set.execute(
        SetApplicationFeeCommand(
            academy_id=academy_id,
            application_fee_bps=payload.application_fee_bps,
            actor_id=claims.user_id,
            reason=payload.reason,
        )
    )
    return _response(result)
