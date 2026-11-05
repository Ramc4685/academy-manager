"""Admin BFF: ``GET /admin/billing/platform-fee`` — the academy's read-only
view of the CourtMastr processing markup (AI strategy Phase 2 slice A1).

Any academy admin may read it (``require_persona("admin")``, no owner gate):
the rate and the agreement are facts about the academy's own billing, not a
money action. Only a PLATFORM admin can change them, through
``interfaces/platform/application_fee_routes.py``.

The reader is attached at ``app.state.admin_platform_fee`` by
``composition/admin_platform_fee.py`` (``composition/admin.py`` is at its line
budget). This module only knows the reader's protocol.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona


class AdminPlatformFeeReader(Protocol):
    async def execute(self) -> Any: ...


def get_admin_platform_fee(request: Request) -> AdminPlatformFeeReader | None:
    return getattr(request.app.state, "admin_platform_fee", None)


class AdminPlatformFeeResponse(BaseModel):
    application_fee_bps: int
    agreement_version: str | None = None
    agreement_text: str
    accepted_at: datetime | None = None
    accepted_by: str | None = None


router = APIRouter(tags=["admin.billing.platform_fee"])


@router.get("/billing/platform-fee", response_model=AdminPlatformFeeResponse)
async def read_platform_fee(
    _claims: AuthClaims = Depends(require_persona("admin")),
    reader: AdminPlatformFeeReader | None = Depends(get_admin_platform_fee),
) -> AdminPlatformFeeResponse:
    """The processing markup this academy pays on Stripe-collected payments,
    with the agreement text and its acceptance status."""
    if reader is None:
        raise HTTPException(status_code=503, detail="platform fee is unavailable")
    result = await reader.execute()
    return AdminPlatformFeeResponse(
        application_fee_bps=result.application_fee_bps,
        agreement_version=result.agreement_version,
        agreement_text=result.agreement_text,
        accepted_at=result.accepted_at,
        accepted_by=result.accepted_by,
    )
