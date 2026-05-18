"""Parent payment + checkout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    BillingPortalRequest,
    BillingPortalResponse,
    CheckoutStatusResponse,
    ParentPaymentHistoryResponse,
    ParentPaymentView,
    StartAutopayRequest,
    StartAutopayResponse,
    StartCheckoutRequest,
    StartCheckoutResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.payments"])


@router.post(
    "/checkout/start",
    response_model=StartCheckoutResponse,
    summary="Create a Stripe Checkout Session for the parent's selected session",
)
async def start_checkout(
    body: StartCheckoutRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> StartCheckoutResponse:
    result = await use_cases.start_checkout_for_application(  # type: ignore[operator]
        parent_id=claims.user_id,
        application_id=body.application_id,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    return StartCheckoutResponse(payment_id=result.payment_id, redirect_url=result.redirect_url)


@router.post(
    "/autopay/start",
    response_model=StartAutopayResponse,
    summary="Create a Stripe subscription checkout session for autopay",
)
async def start_autopay(
    body: StartAutopayRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> StartAutopayResponse:
    result = await use_cases.start_autopay_for_enrollment(  # type: ignore[operator]
        parent_id=claims.user_id,
        enrollment_id=body.enrollment_id,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    return StartAutopayResponse(
        subscription_id=result.subscription_id,
        redirect_url=result.redirect_url,
    )


@router.post(
    "/billing/portal",
    response_model=BillingPortalResponse,
    summary="Create a Stripe customer portal session",
)
async def open_billing_portal(
    body: BillingPortalRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> BillingPortalResponse:
    result = await use_cases.open_billing_portal(  # type: ignore[operator]
        parent_id=claims.user_id,
        return_url=body.return_url,
    )
    return BillingPortalResponse(redirect_url=result["redirect_url"])


@router.get(
    "/checkout/status/{checkout_session_id}",
    response_model=CheckoutStatusResponse,
    summary="Poll checkout status after returning from Stripe",
)
async def checkout_status(
    checkout_session_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CheckoutStatusResponse:
    result = await use_cases.get_checkout_status(  # type: ignore[operator]
        parent_id=claims.user_id,
        checkout_session_id=checkout_session_id,
    )
    return CheckoutStatusResponse(**result)


@router.get(
    "/payments",
    response_model=ParentPaymentHistoryResponse,
    summary="Parent's own payment history",
)
async def list_payments(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentPaymentHistoryResponse:
    payments = await use_cases.list_payments_for_parent(claims.user_id)  # type: ignore[operator]
    return ParentPaymentHistoryResponse(
        payments=[
            ParentPaymentView(
                payment_id=p.payment_id,
                amount_cents=p.amount_cents,
                currency=p.currency,
                status=p.status,
                refunded_cents=p.refunded_cents,
                created_at=p.created_at,
                session_id=p.session_id,
            )
            for p in payments
        ]
    )
