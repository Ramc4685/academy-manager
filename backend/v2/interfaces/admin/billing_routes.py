"""Admin billing routes — academy-wide payments + refunds + finance."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints

from backend.v2.contexts.billing.application.ports import StripeResourceNotFound
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
from backend.v2.contexts.billing.application.use_cases.tuition_discounts import (
    RemoveTuitionDiscountCommand,
    SetTuitionDiscountCommand,
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
    AdminTuitionDiscountSummaryResponse,
    ApplyPaymentDiscountRequest,
    BillingReconciliationReportResponse,
    BillingWebhookQueueResponse,
    ChargeAutopayResponse,
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
    SendInvoiceResponse,
    SetTuitionDiscountRequest,
    WithdrawalCreditApproveRequest,
    WithdrawalCreditApproveResponse,
    WithdrawalCreditPreviewRequest,
    WithdrawalCreditPreviewResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.ids import new_ulid

router = APIRouter(tags=["admin.billing"])


def _required_callable(use_case: object | None, name: str) -> object:
    if use_case is None:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return use_case


@router.get("/billing/invoices", response_model=InvoicesResponse, response_model_exclude_none=True)
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
                line_type=line.get("line_type"),  # type: ignore[arg-type]
                quantity=line.get("quantity"),  # type: ignore[arg-type]
                unit_amount_cents=line.get("unit_amount_cents"),  # type: ignore[arg-type]
                source_type=line.get("source_type"),  # type: ignore[arg-type]
                source_id=line.get("source_id"),  # type: ignore[arg-type]
            )
            for line in item["lines"]
        ]
        total = int(inv.get("total_cents", 0))
        balance = int(inv.get("balance_due_cents", 0))
        invoices.append(
            InvoiceDto(
                invoice_number=str(inv.get("invoice_number") or inv.get("invoice_id", "")),
                period=str(inv.get("period", "")),
                lines=lines,
                total_cents=total,
                paid_cents=max(0, total - balance),
                balance_cents=balance,
                status=str(inv.get("status", "open")),
            )
        )
    return InvoicesResponse(invoices=invoices)


@router.get(
    "/billing/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    response_model_exclude_none=True,
)
async def get_billing_invoice_detail(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceDetailResponse:
    raw = await use_cases.get_billing_invoice_detail(invoice_id)  # type: ignore[operator]
    return InvoiceDetailResponse(
        invoice_id=raw.get("invoice_id"),  # type: ignore[arg-type]
        invoice_number=str(raw["invoice_number"]),
        period=str(raw.get("period") or ""),
        lines=[
            InvoiceLineDto(
                line_id=line.get("line_id"),
                invoice_id=line.get("invoice_id"),
                description=str(line.get("description", "")),
                amount_cents=int(line.get("amount_cents", 0)),
                line_type=line.get("line_type"),  # type: ignore[arg-type]
                quantity=line.get("quantity"),  # type: ignore[arg-type]
                unit_amount_cents=line.get("unit_amount_cents"),  # type: ignore[arg-type]
                source_type=line.get("source_type"),  # type: ignore[arg-type]
                source_id=line.get("source_id"),  # type: ignore[arg-type]
            )
            for line in raw.get("lines", [])
        ],
        subtotal_cents=raw.get("subtotal_cents"),  # type: ignore[arg-type]
        discount_cents=raw.get("discount_cents"),  # type: ignore[arg-type]
        total_cents=raw.get("total_cents"),  # type: ignore[arg-type]
        balance_due_cents=raw.get("balance_due_cents"),  # type: ignore[arg-type]
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
        delivery_status=str(raw.get("delivery_status") or "not_sent"),
        sent_at=raw.get("sent_at"),  # type: ignore[arg-type]
        last_sent_at=raw.get("last_sent_at"),  # type: ignore[arg-type]
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


@router.put("/enrollments/{enrollment_id}/tuition-discount")
async def set_tuition_discount(
    enrollment_id: str,
    body: SetTuitionDiscountRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.set_tuition_discount.execute(
        SetTuitionDiscountCommand(
            discount_id=str(new_ulid()),
            enrollment_id=enrollment_id,
            student_id=body.student_id,
            category=body.category,
            category_label=body.category_label,
            kind=body.kind,
            percent_bps=body.percent_bps,
            amount_off_cents=body.amount_off_cents,
            fixed_net_cents=body.fixed_net_cents,
            effective_start=body.effective_start,
            effective_end=body.effective_end,
            note=body.note,
            set_by=claims.user_id,
        )
    )
    return {"ok": True}


@router.delete("/enrollments/{enrollment_id}/tuition-discount")
async def remove_tuition_discount(
    enrollment_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    await use_cases.remove_tuition_discount.execute(
        RemoveTuitionDiscountCommand(enrollment_id=enrollment_id, ended_by=claims.user_id)
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
        raise HTTPException(
            status_code=503,
            detail="Billing reconciliation is temporarily unavailable. Try again shortly.",
        )
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


@router.get("/billing/reconciliation", response_model=BillingReconciliationReportResponse)
async def get_billing_reconciliation_report(
    stripe_invoice_id: str | None = None,
    payment_intent_id: str | None = None,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingReconciliationReportResponse:
    if not stripe_invoice_id and not payment_intent_id:
        raise HTTPException(
            status_code=422,
            detail="stripe_invoice_id or payment_intent_id is required",
        )
    report = _required_callable(
        use_cases.get_billing_reconciliation_report,
        "Billing reconciliation report",
    )
    try:
        result = await report(
            stripe_invoice_id=stripe_invoice_id,
            payment_intent_id=payment_intent_id,
        )
    except StripeResourceNotFound as exc:
        # str(exc) carries the raw provider error and the internal id — surface
        # a generic message instead.
        raise HTTPException(
            status_code=404,
            detail="That billing record could not be found. Check the ID and try again.",
        ) from exc
    return BillingReconciliationReportResponse(**result)


@router.get("/billing/webhooks", response_model=BillingWebhookQueueResponse)
async def list_billing_webhook_events(
    status: str | None = None,
    limit: int = 50,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingWebhookQueueResponse:
    queue = _required_callable(use_cases.list_billing_webhook_events, "Billing webhook queue")
    rows = await queue(status=status, limit=max(1, min(limit, 100)))
    return BillingWebhookQueueResponse(events=rows)


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


@router.get(
    "/finance/tuition-discounts",
    response_model=AdminTuitionDiscountSummaryResponse,
)  # FINANCE
async def tuition_discount_summary(
    period: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminTuitionDiscountSummaryResponse:
    query = _required_callable(use_cases.tuition_discount_summary, "Tuition discount summary")
    summary = await query.execute(period)  # type: ignore[attr-defined]
    data = summary.model_dump(mode="python") if hasattr(summary, "model_dump") else summary
    return AdminTuitionDiscountSummaryResponse(**data)


# --- Ledger invoice management routes (Phase 2A) ---


class AddInvoiceLineRequest(BaseModel):
    product_id: str | None = None  # informational — prefills name/price/type at call site
    description: str = Field(min_length=1)
    line_type: str = Field(min_length=1)
    quantity: int = Field(ge=1, default=1)
    unit_amount_cents: int = Field(ge=0)


class AddInvoiceAdjustmentRequest(BaseModel):
    description: str = Field(min_length=1)
    amount_cents: int
    reason: str = Field(min_length=1)


class InvoiceLineResponse(BaseModel):
    line_id: str
    invoice_id: str
    line_type: str
    description: str
    quantity: int
    unit_amount_cents: int
    amount_cents: int
    invoice_total_cents: int
    invoice_balance_due_cents: int
    invoice_status: str


class CreateStudentInvoiceRequest(BaseModel):
    student_id: str
    parent_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    due_date: date
    enrollment_id: str | None = None


class VoidInvoiceRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


async def _validate_student_invoice_scope(
    use_cases: AdminUseCases,
    *,
    student_id: str,
    parent_id: str,
    enrollment_id: str | None,
) -> None:
    if use_cases.get_admin_student is None:
        raise HTTPException(status_code=503, detail="Admin student detail is not configured")
    try:
        student = await use_cases.get_admin_student.execute(student_id)
    except Exception as exc:
        if getattr(exc, "code", "") == "Enrollment.StudentNotFound":
            raise HTTPException(status_code=404, detail="student not found") from exc
        raise

    if student.parent_id != parent_id:
        raise HTTPException(status_code=409, detail="invoice parent must match student parent")

    if enrollment_id is None:
        return

    if not any(session.enrollment_id == enrollment_id for session in student.enrolled_sessions):
        raise HTTPException(status_code=409, detail="invoice enrollment must belong to student")


@router.post(
    "/billing/invoices/{invoice_id}/send",
    response_model=SendInvoiceResponse,
)
async def send_billing_invoice(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SendInvoiceResponse:
    """Send (or re-send) an invoice to the parent.

    - Finalizes draft invoices before sending (draft → open).
    - Records delivery status (delivery axis only — financial status unchanged).
    - Returns a Stripe Checkout URL when a balance is outstanding (stubbed if
      Stripe is not configured in the current environment).
    """
    send_invoice = _required_callable(use_cases.send_billing_invoice, "Invoice sending")
    try:
        result = await send_invoice(invoice_id)  # type: ignore[operator]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SendInvoiceResponse(
        invoice_id=str(result["invoice_id"]),
        delivery_status=str(result["delivery_status"]),
        sent_at=result["sent_at"],
        last_sent_at=result["last_sent_at"],
        checkout_url=result["checkout_url"],
    )


@router.post(
    "/billing/invoices/{invoice_id}/charge-autopay",
    response_model=ChargeAutopayResponse,
)
async def charge_invoice_via_autopay(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ChargeAutopayResponse:
    """Charge the invoice balance via the parent's saved Stripe payment method (off-session).

    - Returns success=True when the PI succeeds immediately and the ledger is updated.
    - Returns success=False with decline_code on card declines (invoice status unchanged).
    - Returns success=False with requires_action=True when 3DS is needed (invoice unchanged).
    - Raises 503 when Stripe is not configured.
    - Raises 404 when the invoice is not found.
    - Raises 409 when the invoice is not chargeable (paid/void/draft with zero balance)
      or the parent has no saved payment method.
    """
    charge_autopay = _required_callable(
        use_cases.charge_invoice_via_autopay,
        "Stripe autopay",
    )
    try:
        result = await charge_autopay(invoice_id)  # type: ignore[operator]
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return ChargeAutopayResponse(
        invoice_id=str(result["invoice_id"]),
        success=bool(result["success"]),
        status=str(result["status"]),
        balance_due_cents=int(result["balance_due_cents"]),
        requires_action=bool(result["requires_action"]),
        decline_code=result["decline_code"],
    )


@router.post(
    "/billing/invoices/{invoice_id}/lines",
    response_model=InvoiceLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_invoice_line(
    invoice_id: str,
    body: AddInvoiceLineRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceLineResponse:
    add_line = _required_callable(use_cases.add_invoice_line, "Invoice line management")
    try:
        result = await add_line(  # type: ignore[operator]
            invoice_id=invoice_id,
            description=body.description,
            line_type=body.line_type,
            quantity=body.quantity,
            unit_amount_cents=body.unit_amount_cents,
            product_id=body.product_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    line = result["line"]
    invoice = result["invoice"]
    return InvoiceLineResponse(
        line_id=str(line["line_id"]),
        invoice_id=str(line["invoice_id"]),
        line_type=str(line["line_type"]),
        description=str(line["description"]),
        quantity=int(line["quantity"]),
        unit_amount_cents=int(line["unit_amount_cents"]),
        amount_cents=int(line["amount_cents"]),
        invoice_total_cents=int(invoice["total_cents"]),
        invoice_balance_due_cents=int(invoice["balance_due_cents"]),
        invoice_status=str(invoice["status"]),
    )


@router.post(
    "/billing/invoices/{invoice_id}/adjustments",
    response_model=InvoiceLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_invoice_adjustment(
    invoice_id: str,
    body: AddInvoiceAdjustmentRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceLineResponse:
    add_line = _required_callable(use_cases.add_invoice_line, "Invoice adjustment management")
    try:
        result = await add_line(  # type: ignore[operator]
            invoice_id=invoice_id,
            description=body.description,
            line_type="adjustment",
            quantity=1,
            unit_amount_cents=body.amount_cents,
            product_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    line = result["line"]
    invoice = result["invoice"]
    return InvoiceLineResponse(
        line_id=str(line["line_id"]),
        invoice_id=str(line["invoice_id"]),
        line_type=str(line["line_type"]),
        description=str(line["description"]),
        quantity=int(line["quantity"]),
        unit_amount_cents=int(line["unit_amount_cents"]),
        amount_cents=int(line["amount_cents"]),
        invoice_total_cents=int(invoice["total_cents"]),
        invoice_balance_due_cents=int(invoice["balance_due_cents"]),
        invoice_status=str(invoice["status"]),
    )


@router.delete(
    "/billing/invoices/{invoice_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_invoice_line(
    invoice_id: str,
    line_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    remove_line = _required_callable(use_cases.remove_invoice_line, "Invoice line management")
    try:
        await remove_line(invoice_id=invoice_id, line_id=line_id)  # type: ignore[operator]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc


@router.post("/billing/invoices/{invoice_id}/void", status_code=status.HTTP_200_OK)
async def void_invoice_route(
    invoice_id: str,
    body: VoidInvoiceRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, bool]:
    void_invoice_ = _required_callable(use_cases.void_billing_invoice, "Invoice voiding")
    try:
        await void_invoice_(invoice_id=invoice_id, reason=body.reason)  # type: ignore[operator]
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return {"ok": True}


class RecordManualPaymentRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    payment_method: str = "cash"
    reference_number: str | None = None
    notes: str = ""


class RecordManualPaymentResponse(BaseModel):
    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int


class InvoiceRefundRequest(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0)
    reason: str = "admin_initiated"


class InvoiceRefundResponse(BaseModel):
    invoice_id: str
    payment_id: str
    stripe_refund_id: str
    refunded_cents: int
    total_refunded_cents: int


@router.post(
    "/billing/invoices/{invoice_id}/record-payment",
    response_model=RecordManualPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_manual_payment(
    invoice_id: str,
    body: RecordManualPaymentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> RecordManualPaymentResponse:
    """Record a manual payment (cash, check, etc.) against a ledger invoice.

    Creates a LedgerPayment and allocates it to the invoice balance.
    Partial payments are allowed; the invoice status updates accordingly.
    """
    record_payment = _required_callable(use_cases.record_manual_payment, "Manual payment recording")
    try:
        result = await record_payment(  # type: ignore[operator]
            invoice_id=invoice_id,
            amount_cents=body.amount_cents,
            payment_method=body.payment_method,
            reference_number=body.reference_number,
            notes=body.notes,
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return RecordManualPaymentResponse(
        invoice_id=str(result["invoice_id"]),
        payment_id=str(result["payment_id"]),
        invoice_status=str(result["invoice_status"]),
        balance_due_cents=int(result["balance_due_cents"]),
    )


@router.post(
    "/billing/invoices/{invoice_id}/refund",
    response_model=InvoiceRefundResponse,
)
async def refund_invoice(
    invoice_id: str,
    body: InvoiceRefundRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceRefundResponse:
    issue_refund = _required_callable(use_cases.issue_invoice_refund, "Invoice refund")
    try:
        result = await issue_refund(  # type: ignore[operator]
            invoice_id=invoice_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return InvoiceRefundResponse(
        invoice_id=str(result["invoice_id"]),
        payment_id=str(result["payment_id"]),
        stripe_refund_id=str(result["stripe_refund_id"]),
        refunded_cents=int(result["refunded_cents"]),
        total_refunded_cents=int(result["total_refunded_cents"]),
    )


@router.get(
    "/billing/invoices/{invoice_id}/audit",
    summary="List the append-only billing audit trail for an invoice",
)
async def list_invoice_audit(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict[str, list[dict[str, object]]]:
    lister = _required_callable(use_cases.list_billing_audit, "Billing audit")
    try:
        entries = await lister(invoice_id=invoice_id)  # type: ignore[operator]
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return {"entries": entries}


@router.post(
    "/students/{student_id}/invoices",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_student_invoice(
    student_id: str,
    body: CreateStudentInvoiceRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> dict:
    if body.student_id != student_id:
        raise HTTPException(status_code=409, detail="invoice student must match route student")
    await _validate_student_invoice_scope(
        use_cases,
        student_id=student_id,
        parent_id=body.parent_id,
        enrollment_id=body.enrollment_id,
    )
    create_invoice = _required_callable(use_cases.create_student_invoice, "Invoice creation")
    return await create_invoice(  # type: ignore[operator]
        student_id=student_id,
        parent_id=body.parent_id,
        period=body.period,
        due_date=body.due_date,
        enrollment_id=body.enrollment_id,
    )


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


# --------------------------------------------------------------------------- #
# Billing Health (#235): reconciliation runs, failed payments, webhook replay
# --------------------------------------------------------------------------- #
class ReconciliationRunDto(BaseModel):
    model_config = {"extra": "ignore"}

    run_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    scanned: int = 0
    repaired: int = 0
    skipped: int = 0
    quarantined: int = 0
    failed: int = 0
    errors: list[Any] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReconciliationRunsResponse(BaseModel):
    runs: list[ReconciliationRunDto]


class FailedPaymentRowDto(BaseModel):
    model_config = {"extra": "ignore"}

    invoice_id: str
    parent_id: str
    parent_name: str | None = None
    period: str
    total_cents: int
    balance_due_cents: int
    currency: str = "usd"
    latest_attempt_at: datetime | None = None
    latest_decline_code: str | None = None
    attempt_count: int = 0


class FailedPaymentsResponse(BaseModel):
    rows: list[FailedPaymentRowDto]


class DunningRowDto(BaseModel):
    model_config = {"extra": "ignore"}

    invoice_id: str
    parent_id: str
    parent_name: str | None = None
    period: str
    status: str
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_failure_code: str | None = None
    terminal_at: datetime | None = None
    autopay_disable_status: str | None = None
    autopay_disable_error: str | None = None
    autopay_disabled_at: datetime | None = None
    balance_due_cents: int
    currency: str = "usd"


class DunningResponse(BaseModel):
    rows: list[DunningRowDto]


class PaymentAttemptDto(BaseModel):
    model_config = {"extra": "ignore"}

    attempt_id: str
    status: str
    amount_cents: int
    currency: str = "usd"
    stripe_payment_intent_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    created_at: datetime | None = None


class InvoiceAttemptsResponse(BaseModel):
    attempts: list[PaymentAttemptDto]


class ReplayWebhookResponse(BaseModel):
    replayed: bool
    event_id: str


@router.get("/billing/reconciliation-runs", response_model=ReconciliationRunsResponse)
async def list_reconciliation_runs(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReconciliationRunsResponse:
    list_runs = _required_callable(use_cases.list_reconciliation_runs, "Reconciliation runs")
    rows = await list_runs()  # type: ignore[operator]
    return ReconciliationRunsResponse(runs=[ReconciliationRunDto(**r) for r in rows])


@router.post("/billing/reconcile-now", response_model=ReconciliationRunDto)
async def run_reconciliation_now(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReconciliationRunDto:
    run = _required_callable(use_cases.run_reconciliation, "Reconciliation")
    try:
        result = await run()  # type: ignore[operator]
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReconciliationRunDto(**result)


@router.get("/billing/failed-payment-attempts", response_model=FailedPaymentsResponse)
async def list_failed_payment_attempts(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> FailedPaymentsResponse:
    list_failed = _required_callable(
        use_cases.list_failed_payment_attempts, "Failed payment attempts"
    )
    rows = await list_failed()  # type: ignore[operator]
    return FailedPaymentsResponse(rows=[FailedPaymentRowDto(**r) for r in rows])


@router.get("/billing/dunning", response_model=DunningResponse)
async def list_dunning_failures(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> DunningResponse:
    list_dunning = _required_callable(use_cases.list_dunning_failures, "Dunning failures")
    rows = await list_dunning()  # type: ignore[operator]
    return DunningResponse(rows=[DunningRowDto(**r) for r in rows])


@router.get(
    "/billing/invoices/{invoice_id}/attempts",
    response_model=InvoiceAttemptsResponse,
)
async def list_invoice_attempts(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> InvoiceAttemptsResponse:
    list_attempts = _required_callable(use_cases.list_invoice_attempts, "Invoice attempts")
    try:
        rows = await list_attempts(invoice_id)  # type: ignore[operator]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InvoiceAttemptsResponse(attempts=[PaymentAttemptDto(**a) for a in rows])


@router.post(
    "/billing/webhook-events/{event_id}/replay",
    response_model=ReplayWebhookResponse,
)
async def replay_webhook_event(
    event_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ReplayWebhookResponse:
    replay = _required_callable(use_cases.replay_webhook_event, "Webhook replay")
    try:
        await replay(event_id)  # type: ignore[operator]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReplayWebhookResponse(replayed=True, event_id=event_id)


# --------------------------------------------------------------------------- #
# Legacy invoice ↔ Stripe charge review queue (#242 WI-3)
# --------------------------------------------------------------------------- #
class LegacyMatchCandidateDto(BaseModel):
    model_config = {"extra": "ignore"}

    stripe_charge_id: str
    stripe_payment_intent_id: str | None = None
    amount_cents: int
    currency: str = "usd"
    created_at: datetime | None = None
    description: str | None = None
    confidence: str


class LegacyMatchRowDto(BaseModel):
    model_config = {"extra": "ignore"}

    invoice_id: str
    parent_id: str
    parent_name: str | None = None
    period: str
    status: str
    total_cents: int
    balance_due_cents: int
    currency: str = "usd"
    due_date: date | None = None
    created_at: datetime | None = None
    stripe_invoice_id: str | None = None
    stripe_customer_id: str | None = None
    candidates: list[LegacyMatchCandidateDto] = Field(default_factory=list)


class LegacyMatchQueueResponse(BaseModel):
    rows: list[LegacyMatchRowDto]


class ConfirmLegacyMatchRequest(BaseModel):
    invoice_id: str
    stripe_charge_id: str
    amount_cents: int = Field(gt=0)
    stripe_payment_intent_id: str | None = None
    paid_at: datetime | None = None


class ConfirmLegacyMatchResponse(BaseModel):
    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int


@router.get("/billing/legacy-match-queue", response_model=LegacyMatchQueueResponse)
async def list_legacy_match_queue(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> LegacyMatchQueueResponse:
    list_queue = _required_callable(use_cases.list_legacy_match_queue, "Legacy match queue")
    try:
        rows = await list_queue()  # type: ignore[operator]
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LegacyMatchQueueResponse(rows=[LegacyMatchRowDto(**r) for r in rows])


@router.post("/billing/legacy-match/confirm", response_model=ConfirmLegacyMatchResponse)
async def confirm_legacy_match(
    body: ConfirmLegacyMatchRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ConfirmLegacyMatchResponse:
    confirm = _required_callable(use_cases.confirm_legacy_match, "Legacy match confirm")
    try:
        result = await confirm(  # type: ignore[operator]
            invoice_id=body.invoice_id,
            stripe_charge_id=body.stripe_charge_id,
            amount_cents=body.amount_cents,
            stripe_payment_intent_id=body.stripe_payment_intent_id,
            paid_at=body.paid_at,
            recorded_by=claims.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConfirmLegacyMatchResponse(**result)
