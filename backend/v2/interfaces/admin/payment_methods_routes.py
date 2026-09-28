"""Admin BFF: ``/admin/academy/payment-methods`` (Settings -> Billing rules ->
Offline payments).

The read is open to the ``billing`` staff tier as well as admins, because
billing staff record payments and their dialogs list these methods. The write
is **owner only** (listed in ``OWNER_ONLY_ROUTE_PATHS``) and audited: it is a
money setting. The use cases are attached at ``app.state.admin_payment_methods``
by ``composition/payment_methods.py``.
"""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.manual_payment_methods import (
    ManualPaymentMethodsValidationError,
    UpdateManualPaymentMethodsCommand,
)
from backend.v2.interfaces.admin.staff_tier import require_staff_tier
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner


class PaymentMethodsResponse(BaseModel):
    manual_methods: list[str]


class UpdatePaymentMethodsRequest(BaseModel):
    """The use case owns the rules (known methods, at least one) so one code
    path names the 422; here only the size is bounded."""

    manual_methods: list[Annotated[str, Field(max_length=32)]] = Field(max_length=20)
    reason: str | None = Field(default=None, max_length=500)


class _Reader(Protocol):
    async def execute(self, academy_id: str) -> list[str]: ...


class _Writer(Protocol):
    async def execute(self, academy_id: str, cmd: UpdateManualPaymentMethodsCommand) -> Any: ...


class AdminPaymentMethodsLike(Protocol):
    read: _Reader
    write: _Writer


def get_admin_payment_methods(request: Request) -> AdminPaymentMethodsLike:
    methods: AdminPaymentMethodsLike = request.app.state.admin_payment_methods
    return methods


router = APIRouter(tags=["admin.payment-methods"])


@router.get(
    "/academy/payment-methods",
    response_model=PaymentMethodsResponse,
    summary="Offline payment methods the payment dialogs offer",
)
async def get_payment_methods(
    claims: AuthClaims = Depends(require_staff_tier("billing")),
    methods: AdminPaymentMethodsLike = Depends(get_admin_payment_methods),
) -> PaymentMethodsResponse:
    return PaymentMethodsResponse(manual_methods=await methods.read.execute(claims.academy_id))


@router.put(
    "/academy/payment-methods",
    response_model=PaymentMethodsResponse,
    summary="Choose the offline payment methods (owner only, audited)",
)
async def set_payment_methods(
    body: UpdatePaymentMethodsRequest,
    claims: AuthClaims = Depends(require_owner()),
    methods: AdminPaymentMethodsLike = Depends(get_admin_payment_methods),
) -> PaymentMethodsResponse:
    try:
        saved = await methods.write.execute(
            claims.academy_id,
            UpdateManualPaymentMethodsCommand(
                manual_methods=body.manual_methods,
                actor_id=claims.user_id,
                reason=body.reason,
            ),
        )
    except ManualPaymentMethodsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"field": exc.field, "message": exc.message},
        ) from exc
    return PaymentMethodsResponse(manual_methods=list(saved))
