"""Parent invoice read routes.

Subscription portal note: parents manage their subscription/billing portal via
the existing ``POST /parent/billing/portal`` route (see ``payment_routes.py``).
No duplicate portal route is added here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentInvoiceDetailView,
    ParentInvoiceLineView,
    ParentInvoicesResponse,
    ParentInvoiceView,
    StartInvoicePaymentRequest,
    StartInvoicePaymentResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.invoices"])


def _pdf_url(invoice) -> str | None:
    # pdf_artifact_id is an internal store reference, not a public URL.
    # Return None until a URL resolver is wired up.
    return None


def _invoice_view(invoice) -> ParentInvoiceView:
    return ParentInvoiceView(
        invoice_id=invoice.invoice_id,
        period=invoice.period,
        status=invoice.status,
        total_cents=invoice.total_cents,
        balance_due_cents=invoice.balance_due_cents,
        currency=invoice.currency,
        due_date=invoice.due_date,
        pdf_url=_pdf_url(invoice),
        created_at=invoice.created_at,
    )


def _required_callable(use_case: object | None, name: str) -> object:
    if use_case is None:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return use_case


@router.get(
    "/invoices",
    response_model=ParentInvoicesResponse,
    summary="Parent's own invoices",
)
async def list_invoices(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentInvoicesResponse:
    invoices = await use_cases.list_invoices_for_parent(claims.user_id)  # type: ignore[operator]
    return ParentInvoicesResponse(invoices=[_invoice_view(inv) for inv in invoices])


@router.get(
    "/invoices/{invoice_id}",
    response_model=ParentInvoiceDetailView,
    summary="Parent invoice detail with line items",
)
async def get_invoice(
    invoice_id: str,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentInvoiceDetailView:
    result = await use_cases.get_invoice_for_parent(  # type: ignore[operator]
        parent_id=claims.user_id,
        invoice_id=invoice_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    invoice = result["invoice"]
    lines = result["lines"]
    base = _invoice_view(invoice)
    return ParentInvoiceDetailView(
        **base.model_dump(),
        lines=[
            ParentInvoiceLineView(
                description=line.description,
                quantity=line.quantity,
                unit_amount_cents=line.unit_amount_cents,
                amount_cents=line.amount_cents,
            )
            for line in lines
        ],
    )


@router.post(
    "/invoices/{invoice_id}/pay",
    response_model=StartInvoicePaymentResponse,
    summary="Create a Stripe Checkout Session to retry paying an open invoice",
)
async def start_invoice_payment(
    invoice_id: str,
    body: StartInvoicePaymentRequest,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> StartInvoicePaymentResponse:
    start_payment = _required_callable(
        use_cases.start_invoice_payment_for_parent,
        "Invoice payment retry",
    )
    try:
        result = await start_payment(
            parent_id=claims.user_id,
            invoice_id=invoice_id,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Not found")
    return StartInvoicePaymentResponse(
        invoice_id=str(result["invoice_id"]),
        redirect_url=str(result["checkout_url"]),
    )
