"""Admin billing routes — academy-wide payments + refunds + finance."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    RecordExpenseCommand,
)
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscountCommand,
    GenerateMonthlyPaymentsCommand,
    MarkPaymentPaidCommand,
    UndoPaymentPaidCommand,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import (
    IssueRefundCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminExpenseList,
    AdminExpenseView,
    AdminPaymentList,
    AdminPaymentView,
    AdminPayoutList,
    AdminPayoutView,
    AdminRevenueResponse,
    ApplyPaymentDiscountRequest,
    GenerateMonthlyPaymentsRequest,
    GenerateMonthlyPaymentsResponse,
    IssueRefundRequest,
    MarkPaymentPaidRequest,
    RecordExpenseRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.billing"])


@router.get("/payments", response_model=AdminPaymentList)
async def list_payments(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPaymentList:
    rows = await use_cases.list_payments_recent()  # type: ignore[operator]
    return AdminPaymentList(
        payments=[_payment_view(p) for p in rows]
    )


@router.post("/payments/refund", summary="Issue a refund")
async def refund(
    body: IssueRefundRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, object]:
    result = await use_cases.issue_refund.execute(
        IssueRefundCommand(
            payment_id=body.payment_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
        )
    )
    return result.model_dump()


@router.post("/payments/generate-monthly", response_model=GenerateMonthlyPaymentsResponse)
async def generate_monthly_payments(
    body: GenerateMonthlyPaymentsRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> GenerateMonthlyPaymentsResponse:
    result = await use_cases.generate_monthly_payments.execute(
        GenerateMonthlyPaymentsCommand(period=body.period)
    )
    return GenerateMonthlyPaymentsResponse(**result.model_dump())


@router.post("/payments/{payment_id}/mark-paid")
async def mark_payment_paid(
    payment_id: str,
    body: MarkPaymentPaidRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.mark_payment_paid.execute(
        MarkPaymentPaidCommand(
            payment_id=payment_id,
            payment_method=body.payment_method,
            notes=body.notes,
        )
    )
    return {"ok": True}


@router.post("/payments/{payment_id}/discount")
async def apply_payment_discount(
    payment_id: str,
    body: ApplyPaymentDiscountRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.apply_payment_discount.execute(
        ApplyPaymentDiscountCommand(
            payment_id=payment_id,
            discount_cents=body.discount_cents,
        )
    )
    return {"ok": True}


@router.post("/payments/{payment_id}/undo-paid")
async def undo_payment_paid(
    payment_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.undo_payment_paid.execute(UndoPaymentPaidCommand(payment_id=payment_id))
    return {"ok": True}


# --- # FINANCE ---


@router.get("/finance/payouts", response_model=AdminPayoutList)  # FINANCE
async def list_payouts(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutList:
    payouts = await use_cases.payouts.list_all()
    return AdminPayoutList(
        payouts=[
            AdminPayoutView(
                payout_id=p.payout_id,
                coach_id=p.coach_id,
                amount_cents=p.amount_cents,
                period_start=p.period_start,
                period_end=p.period_end,
                paid_at=p.paid_at,
            )
            for p in payouts
        ]
    )


@router.get("/finance/expenses", response_model=AdminExpenseList)  # FINANCE
async def list_expenses(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminExpenseList:
    expenses = await use_cases.expenses.list_recent()
    return AdminExpenseList(
        expenses=[
            AdminExpenseView(
                expense_id=e.expense_id,
                category=e.category,
                amount_cents=e.amount_cents,
                note=e.note,
                incurred_on=e.incurred_on,
            )
            for e in expenses
        ]
    )


@router.post("/finance/expenses", response_model=AdminExpenseView)  # FINANCE
async def record_expense(
    body: RecordExpenseRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminExpenseView:
    e = await use_cases.record_expense.execute(RecordExpenseCommand(**body.model_dump()))
    return AdminExpenseView(
        expense_id=e.expense_id,
        category=e.category,
        amount_cents=e.amount_cents,
        note=e.note,
        incurred_on=e.incurred_on,
    )


@router.get("/finance/revenue", response_model=AdminRevenueResponse)  # FINANCE
async def revenue(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminRevenueResponse:
    # Wave 3 stub aggregates across all parents — replace with Mongo
    # aggregation when scale demands. Promote to Finance context (per
    # ADR-0006 trigger) when this query gets its own aggregates.
    by_month = await use_cases.revenue_query.execute(parent_id_filter=None)
    return AdminRevenueResponse(by_month=by_month)


def _payment_view(row: object) -> AdminPaymentView:
    if isinstance(row, dict):
        return AdminPaymentView(**row)
    amount_cents = getattr(row, "amount_cents")
    return AdminPaymentView(
        payment_id=getattr(row, "payment_id"),
        parent_id=getattr(row, "parent_id"),
        session_id=getattr(row, "session_id"),
        amount_cents=amount_cents,
        discount_cents=0,
        final_amount_cents=amount_cents,
        currency=getattr(row, "currency"),
        status=getattr(row, "status"),
        refunded_cents=getattr(row, "refunded_cents"),
        created_at=getattr(row, "created_at"),
    )
