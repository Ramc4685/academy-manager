"""Parent self-cancel enrollment routes (R4).

GET  /parent/enrollments/{enrollment_id}/cancellation-preview
POST /parent/enrollments/{enrollment_id}/self-cancel

Interface layer only — no domain/infrastructure imports, mirrors
``makeup_routes.py``. Wrong-persona access 404s via ``require_persona``.
Ownership failures (wrong parent / unknown enrollment) surface as
``Enrollment.NotFound`` (404) via the registered exception handlers; they are
never represented as a 200 with ``allowed=False`` (that shape is reserved for
a real, owned enrollment that just isn't cancellable right now).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    SelfCancelEnrollmentCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.self_cancel"])


class CancellationPreviewResponse(BaseModel):
    allowed: bool
    notice_met: bool
    fee_cents: int
    effective_timing: str
    policy: dict[str, Any]
    blocked_reason: str | None


class SelfCancelRequest(BaseModel):
    reason: str = Field(min_length=1)


class SelfCancelResponse(BaseModel):
    enrollment_id: str
    status: str
    fee_cents: int
    effective_timing: str
    cancelled_at: datetime


@router.get(
    "/enrollments/{enrollment_id}/cancellation-preview",
    response_model=CancellationPreviewResponse,
)
async def preview_cancellation(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CancellationPreviewResponse:
    view = await use_cases.preview_self_cancel.execute(  # type: ignore[attr-defined]
        enrollment_id=enrollment_id,
        parent_id=claims.user_id,
    )
    return CancellationPreviewResponse(**view.model_dump())


@router.post(
    "/enrollments/{enrollment_id}/self-cancel",
    response_model=SelfCancelResponse,
)
async def self_cancel_enrollment(
    enrollment_id: str,
    body: SelfCancelRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> SelfCancelResponse:
    result = await use_cases.self_cancel_enrollment.execute(  # type: ignore[attr-defined]
        SelfCancelEnrollmentCommand(
            enrollment_id=enrollment_id,
            parent_id=claims.user_id,
            reason=body.reason,
        )
    )
    return SelfCancelResponse(
        enrollment_id=result.enrollment_id,
        status=result.status,
        fee_cents=result.fee_cents,
        effective_timing=result.effective_timing,
        cancelled_at=result.cancelled_at,
    )
