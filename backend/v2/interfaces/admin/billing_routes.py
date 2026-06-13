"""Admin billing routes — academy-wide payments + refunds + finance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscountCommand,
    GenerateMonthlyPaymentsCommand,
    MarkPaymentPaidCommand,
    UndoPaymentPaidCommand,
)
from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    DeleteExpenseCommand,
    EditExpenseCommand,
    RecordExpenseCommand,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import (
    IssueRefundCommand,
)
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCreditCommand,
    PreviewWithdrawalCreditCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminEnrollmentQuoteRequest,
    AdminEnrollmentQuoteResponse,
    AdminExpenseList,
    AdminExpenseView,
    AdminPaymentList,
    AdminPaymentView,
    AdminPayoutList,
    AdminPayoutView,
    AdminRevenueResponse,
    ApplyPaymentDiscountRequest,
    DeleteExpenseRequest,
    EditExpenseRequest,
    GenerateInvoiceArtifactRequest,
    GenerateInvoiceArtifactResponse,
    GenerateMonthlyPaymentsRequest,
    GenerateMonthlyPaymentsResponse,
    InvoiceAllocationDto,
    InvoiceCreditUsageDto,
    InvoiceDetailResponse,
    InvoiceDto,
    InvoiceLineDto,
    InvoicesResponse,
    IssueRefundRequest,
    MarkPaymentPaidRequest,
    ReconcileStripeBillingRequest,
    ReconcileStripeBillingResponse,
    RecordExpenseRequest,
    WithdrawalCreditApproveRequest,
    WithdrawalCreditApproveResponse,
    WithdrawalCreditPreviewRequest,
    WithdrawalCreditPreviewResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.billing"])


@router.get("/billing/invoices", response_model=InvoicesResponse)
async def list_billing_invoices(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoicesResponse:
    raw = await use_cases.list_billing_invoices()
    invoices = []
    for item in raw:
        inv = item["invoice"]
        lines = [
            InvoiceLineDto(
                description=str(line.get("description", "")),
                amount_cents=int(line.get("amount_cents", 0)),
            )
            for line in item["lines"]
        ]
        total = int(inv.get("total_cents", 0))
        balance = int(inv.get("balance_due_cents", 0))
        invoices.append(
            InvoiceDto(
                invoice_number=str(inv.get("invoice_id", "")),
                period=str(inv.get("period", "")),
                lines=lines,
                total_cents=total,
                paid_cents=max(0, total - balance),
                balance_cents=balance,
                status=str(inv.get("status", "open")),
            )
        )
    return InvoicesResponse(invoices=invoices)


@router.get("/billing/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_billing_invoice_detail(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceDetailResponse:
    raw = await use_cases.get_billing_invoice_detail(invoice_id)  # type: ignore[operator]
    return InvoiceDetailResponse(
        invoice_number=str(raw["invoice_number"]),
        period=str(raw.get("period") or ""),
        lines=[
            InvoiceLineDto(
                description=str(line.get("description", "")),
                amount_cents=int(line.get("amount_cents", 0)),
            )
            for line in raw.get("lines", [])
        ],
        due_amount_cents=int(raw.get("due_amount_cents", 0)),
        paid_amount_cents=int(raw.get("paid_amount_cents", 0)),
        status=str(raw.get("status", "open")),
        allocations=[
            InvoiceAllocationDto(
                payment_id=str(item.get("payment_id", "")),
                amount_cents=int(item.get("amount_cents", 0)),
            )
            for item in raw.get("allocations", [])
        ],
        credit_usage=[
            InvoiceCreditUsageDto(
                credit_id=str(item.get("credit_id", "")),
                amount_cents=int(item.get("amount_cents", 0)),
            )
            for item in raw.get("credit_usage", [])
        ],
        invoice_pdf_artifact_id=raw.get("invoice_pdf_artifact_id"),  # type: ignore[arg-type]
        receipt_artifact_id=raw.get("receipt_artifact_id"),  # type: ignore[arg-type]
    )


@router.post(
    "/billing/invoices/{invoice_id}/artifacts",
    response_model=GenerateInvoiceArtifactResponse,
)
async def generate_billing_invoice_artifact(
    invoice_id: str,
    body: GenerateInvoiceArtifactRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> GenerateInvoiceArtifactResponse:
    raw = await use_cases.generate_billing_invoice_artifact(  # type: ignore[operator]
        invoice_id,
        body.artifact_type,
    )
    return GenerateInvoiceArtifactResponse(
        artifact_id=str(raw["artifact_id"]),
        artifact_type=body.artifact_type,
        status="generated",
    )


def _admin_quote_response(snapshot) -> AdminEnrollmentQuoteResponse:
    monthly = snapshot.monthly_price_cents
    total = snapshot.total_eligible_classes
    remaining = snapshot.billable_remaining_classes
    return AdminEnrollmentQuoteResponse(
        snapshot_id=snapshot.snapshot_id or "",
        quote_expires_at=snapshot.expires_at,
        amount_due_cents=snapshot.final_amount_cents,
        monthly_price_cents=monthly,
        billing_period=snapshot.billing_period_label,
        total_eligible_classes_this_month=total,
        billable_remaining_classes_this_month=remaining,
        formula=f"${monthly / 100:.2f} x {remaining} / {total}" if total else "$0.00",
        included_occurrence_ids=snapshot.included_occurrence_ids,
        excluded_occurrences=snapshot.excluded_occurrences,
        policy_version=snapshot.policy_version,
        settings_version=snapshot.settings_version,
        schedule_signature=snapshot.schedule_signature,
    )


@router.post(
    "/enrollments/quote",
    response_model=AdminEnrollmentQuoteResponse,
    summary="Create an admin first-month enrollment billing quote",
)
async def quote_enrollment(
    body: AdminEnrollmentQuoteRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminEnrollmentQuoteResponse:
    snapshot = await use_cases.quote_enrollment(  # type: ignore[operator]
        session_id=body.session_id,
        student_id=body.student_id,
        start_date=body.start_date,
    )
    return _admin_quote_response(snapshot)


@router.post(
    "/enrollments/{enrollment_id}/withdrawal-credit/preview",
    response_model=WithdrawalCreditPreviewResponse,
)
async def preview_withdrawal_credit(
    enrollment_id: str,
    body: WithdrawalCreditPreviewRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> WithdrawalCreditPreviewResponse:
    result = await use_cases.preview_withdrawal_credit.execute(
        PreviewWithdrawalCreditCommand(
            enrollment_id=enrollment_id,
            withdrawal_date=body.withdrawal_date,
            actor_id=claims.user_id,
        )
    )
    return WithdrawalCreditPreviewResponse(
        credit_amount_cents=result.credit_amount_cents,
        display_amount=_format_cents(result.credit_amount_cents),
        total_classes=result.paid_period_eligible_classes,
        unused_classes=result.unused_eligible_classes,
        formula=result.formula,
        message=(
            f"Credit is calculated for {result.unused_eligible_classes} unused classes."
            if result.credit_amount_cents > 0
            else "No withdrawal credit is available for this date."
        ),
        no_credit_reason=result.no_credit_reason,
    )


@router.post(
    "/enrollments/{enrollment_id}/withdrawal-credit/approve",
    response_model=WithdrawalCreditApproveResponse,
)
async def approve_withdrawal_credit(
    enrollment_id: str,
    body: WithdrawalCreditApproveRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> WithdrawalCreditApproveResponse:
    result = await use_cases.approve_withdrawal_credit.execute(
        ApproveWithdrawalCreditCommand(
            enrollment_id=enrollment_id,
            withdrawal_date=body.withdrawal_date,
            actor_id=claims.user_id,
            admin_note=body.admin_note,
            cancel_subscription_immediately=body.cancel_subscription_immediately,
        )
    )
    return WithdrawalCreditApproveResponse(
        status=result.status,
        credit_amount_cents=result.credit_amount_cents,
        credit_balance_cents=result.credit_balance_cents,
    )


@router.get("/payments", response_model=AdminPaymentList)
async def list_payments(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPaymentList:
    rows = await use_cases.list_payments_recent()  # type: ignore[operator]
    return AdminPaymentList(payments=[_payment_view(p) for p in rows])


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
        GenerateMonthlyPaymentsCommand(period=body.period or "")
    )
    return GenerateMonthlyPaymentsResponse(**result.model_dump())


@router.post("/payments/{payment_id}/mark-paid")
async def mark_payment_paid(
    payment_id: str,
    body: MarkPaymentPaidRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.mark_payment_paid.execute(
        MarkPaymentPaidCommand(
            payment_id=payment_id,
            payment_method=body.payment_method,
            amount_received_cents=body.amount_received_cents,
            reference_number=body.reference_number,
            notes=body.notes,
            recorded_by=claims.user_id,
            payment_date=body.payment_date,
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
            reason=body.reason,
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


@router.post("/billing/reconcile", response_model=ReconcileStripeBillingResponse)
async def reconcile_stripe_billing(
    body: ReconcileStripeBillingRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReconcileStripeBillingResponse:
    if use_cases.reconcile_stripe_billing is None:
        raise HTTPException(status_code=503, detail="Stripe billing reconciliation unavailable")
    try:
        result = await use_cases.reconcile_stripe_billing(
            parent_id=body.parent_id,
            enrollment_id=body.enrollment_id,
            stripe_customer_id=body.stripe_customer_id,
            stripe_checkout_session_id=body.stripe_checkout_session_id,
            reason=body.reason,
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReconcileStripeBillingResponse(**result)


# --- # FINANCE ---


# DEPRECATED — retire after feat/coach-payroll-month-first ships.
# Replaced by: GET /admin/payroll/{month} in payroll_routes.py
# No UI surface should call this route once Phase 2 is merged.
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
                expected_revenue_cents=p.expected_revenue_cents,
                students_count=p.students_count,
                sessions_count=p.sessions_count,
                rule_label=p.rule_label,
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


@router.patch("/finance/expenses/{expense_id}", response_model=AdminExpenseView)  # FINANCE
async def edit_expense(
    expense_id: str,
    body: EditExpenseRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminExpenseView:
    e = await use_cases.edit_expense.execute(
        EditExpenseCommand(
            expense_id=expense_id,
            actor_id=claims.user_id,
            **body.model_dump(exclude_unset=True),
        )
    )
    return AdminExpenseView(
        expense_id=e.expense_id,
        category=e.category,
        amount_cents=e.amount_cents,
        note=e.note,
        incurred_on=e.incurred_on,
    )


@router.delete("/finance/expenses/{expense_id}", status_code=204, response_model=None)  # FINANCE
async def delete_expense(
    expense_id: str,
    body: DeleteExpenseRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.delete_expense.execute(
        DeleteExpenseCommand(
            expense_id=expense_id,
            actor_id=claims.user_id,
            reason=body.reason,
        )
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
    amount_cents = row.amount_cents
    return AdminPaymentView(
        payment_id=row.payment_id,
        parent_id=row.parent_id,
        session_id=row.session_id,
        amount_cents=amount_cents,
        discount_cents=0,
        final_amount_cents=amount_cents,
        amount_received_cents=amount_cents if row.status == "succeeded" else 0,
        paid_amount_cents=amount_cents if row.status == "succeeded" else 0,
        balance_due_cents=0 if row.status == "succeeded" else amount_cents,
        overpayment_credit_cents=0,
        currency=row.currency,
        status=row.status,
        refunded_cents=row.refunded_cents,
        created_at=row.created_at,
    )


def _format_cents(cents: int) -> str:
    return f"${cents / 100:.2f}"
