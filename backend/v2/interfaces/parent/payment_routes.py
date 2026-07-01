"""Parent payment + checkout routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    BillingPortalRequest,
    BillingPortalResponse,
    CheckoutStatusResponse,
    EnrollmentQuoteRequest,
    EnrollmentQuoteResponse,
    ParentCreditBalanceResponse,
    ParentCreditView,
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


def _quote_response(snapshot) -> EnrollmentQuoteResponse:
    amount = snapshot.final_amount_cents
    monthly = snapshot.monthly_price_cents
    total = snapshot.total_eligible_classes
    remaining = snapshot.billable_remaining_classes
    return EnrollmentQuoteResponse(
        snapshot_id=snapshot.snapshot_id or "",
        quote_expires_at=snapshot.expires_at,
        amount_due_cents=amount,
        monthly_price_cents=monthly,
        billing_period=snapshot.billing_period_label,
        total_eligible_classes_this_month=total,
        billable_remaining_classes_this_month=remaining,
        formula=f"${monthly / 100:.2f} x {remaining} / {total}" if total else "$0.00",
        message=f"First month is billed for {remaining} of {total} eligible classes this month.",
        next_billing_amount_cents=monthly,
        next_billing_message=f"Starting next month, tuition is ${monthly / 100:.2f}/month.",
    )


@router.post(
    "/enrollments/quote",
    response_model=EnrollmentQuoteResponse,
    summary="Create a parent-safe first-month enrollment billing quote",
)
async def quote_enrollment(
    body: EnrollmentQuoteRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> EnrollmentQuoteResponse:
    snapshot = await use_cases.quote_enrollment(  # type: ignore[operator]
        parent_id=claims.user_id,
        student_id=body.student_id,
        session_id=body.session_id,
        start_date=body.start_date,
    )
    return _quote_response(snapshot)


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
        checkout_session_id=result.checkout_session_id,
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
    request: Request,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> CheckoutStatusResponse:
    result = await use_cases.get_checkout_status(  # type: ignore[operator]
        parent_id=claims.user_id,
        checkout_session_id=checkout_session_id,
        source="parent_checkout_status",
        actor_id=claims.user_id,
        ip=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CheckoutStatusResponse(**result)


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


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
                stripe_invoice_id=getattr(p, "stripe_invoice_id", None),
                stripe_payment_intent_id=getattr(p, "stripe_payment_intent_id", None),
            )
            for p in payments
        ]
    )


@router.get(
    "/credits",
    response_model=ParentCreditBalanceResponse,
    summary="Parent's account credit balance",
)
async def list_credits(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentCreditBalanceResponse:
    credits = await use_cases.list_credits_for_parent(claims.user_id)  # type: ignore[operator]
    # Mirror balance_for_parent / apply_available_credits semantics: only APPROVED,
    # non-expired credits with remaining_amount_cents > 0 are spendable. Showing
    # expired credits in balance_cents would diverge from what we'd actually
    # apply at invoice time.
    now = datetime.now(UTC)
    balance = sum(
        c.remaining_amount_cents
        for c in credits
        if c.status == "APPROVED"
        and c.remaining_amount_cents > 0
        and (c.expires_at is None or c.expires_at > now)
    )
    return ParentCreditBalanceResponse(
        balance_cents=balance,
        credits=[
            ParentCreditView(
                credit_id=c.credit_id,
                type=c.type,
                status=c.status,
                amount_cents=c.amount_cents,
                remaining_amount_cents=c.remaining_amount_cents,
                currency=c.currency,
                reason=c.reason,
                expires_at=c.expires_at,
            )
            for c in credits
        ],
    )
