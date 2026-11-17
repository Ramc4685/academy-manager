"""Admin BFF: ``PUT /admin/enrollments/{enrollment_id}/billing`` — "Not billed" / "Start billing".

Owner only (``OWNER_ONLY_ROUTE_PATHS``): whether a child is invoiced is a
money setting, the same tier as tuition discounts. Audited through the
billing audit log; going forward only. The use case is attached at
``app.state.admin_enrollment_billing`` by ``composition/enrollment_billing.py``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.enrollment_not_billed import (
    EnrollmentNotFound,
    NotBilledValidationError,
    SetEnrollmentBillingCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

NotBilledReasonValue = Literal["owner_child", "coach_child", "scholarship", "other"]


class SetEnrollmentBillingRequest(BaseModel):
    model_config = {"extra": "forbid"}

    #: ``true`` marks the enrollment not billed; ``false`` starts billing again.
    not_billed: bool
    reason: NotBilledReasonValue | None = None
    note: str | None = Field(default=None, max_length=500)
    #: Not billed only: also void this enrollment's open, unpaid invoices.
    void_open_invoices: bool = False


class EnrollmentBillingView(BaseModel):
    enrollment_id: str
    not_billed: bool
    billing_type: str
    not_billed_reason: NotBilledReasonValue | None = None
    not_billed_note: str | None = None
    voided_invoice_ids: list[str] = []
    kept_invoice_ids: list[str] = []
    skipped_period: str | None = None


class _Setter(Protocol):
    async def execute(self, academy_id: str, cmd: SetEnrollmentBillingCommand) -> Any: ...


def get_admin_enrollment_billing(request: Request) -> _Setter:
    setter: _Setter = request.app.state.admin_enrollment_billing
    return setter


router = APIRouter(tags=["admin.enrollment-billing"])


@router.put(
    "/enrollments/{enrollment_id}/billing",
    response_model=EnrollmentBillingView,
    summary="Mark an enrollment not billed, or start billing it (owner only, audited)",
)
async def set_enrollment_billing(
    enrollment_id: str,
    body: SetEnrollmentBillingRequest,
    claims: AuthClaims = Depends(require_owner()),
    setter: _Setter = Depends(get_admin_enrollment_billing),
) -> EnrollmentBillingView:
    try:
        result = await setter.execute(
            claims.academy_id,
            SetEnrollmentBillingCommand(
                enrollment_id=enrollment_id,
                not_billed=body.not_billed,
                reason=body.reason,
                note=body.note,
                void_open_invoices=body.void_open_invoices,
                actor_id=claims.user_id,
            ),
        )
    except EnrollmentNotFound as exc:
        raise HTTPException(status_code=404, detail="enrollment not found") from exc
    except NotBilledValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"field": exc.field, "message": exc.message},
        ) from exc
    return EnrollmentBillingView.model_validate(result.model_dump(mode="json"))
