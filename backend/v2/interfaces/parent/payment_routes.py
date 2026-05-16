"""Parent payment + checkout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckoutCommand,
)
from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentPaymentHistoryResponse,
    ParentPaymentView,
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
    # Pull the application -> session_id binding.
    app = await use_cases.get_application_status.execute(body.application_id)
    assert app.selected_session_id, "application must have a selected session"
    result = await use_cases.start_checkout.execute(
        StartCheckoutCommand(
            parent_id=claims.user_id,
            session_id=app.selected_session_id,
            amount_cents=body.amount_cents,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    )
    # Bind the payment_id back onto the application so event handlers can
    # look it up.
    await use_cases.transition_application.execute(
        app.application_id, "CHECKOUT_PENDING",
        stripe_checkout_session_id=result.checkout_session_id,
        payment_id=result.payment_id,
    )
    return StartCheckoutResponse(payment_id=result.payment_id, redirect_url=result.redirect_url)


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
