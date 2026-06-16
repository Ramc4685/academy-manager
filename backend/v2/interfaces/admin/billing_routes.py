"""Admin billing routes — academy-wide payments + refunds + finance."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, StringConstraints

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscountCommand,
    GenerateMonthlyPaymentsCommand,
    MarkPaymentPaidCommand,
    UndoPaymentPaidCommand,
)
from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    DeleteExpenseCommand,
    EditExpenseCommand,
    RecordExpenseCommand,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import (
    IssueRefundCommand,
)
from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    RecordManualPayment,
    RecordManualPaymentCommand,
)
from backend.v2.contexts.billing.application.use_cases.remove_invoice_line import (
    RemoveInvoiceLine,
    RemoveInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCreditCommand,
    PreviewWithdrawalCreditCommand,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
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
    WithdrawalCreditApproveRequest,
    WithdrawalCreditApproveResponse,
    WithdrawalCreditPreviewRequest,
    WithdrawalCreditPreviewResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.config import get_settings
from backend.v2.shared.http import require_persona
from backend.v2.shared.ids import new_ulid

router = APIRouter(tags=["admin.billing"])


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


# --- Ledger invoice management routes (Phase 2A) ---


class AddInvoiceLineRequest(BaseModel):
    product_id: str | None = None  # informational — prefills name/price/type at call site
    description: str = Field(min_length=1)
    line_type: str = Field(min_length=1)
    quantity: int = Field(ge=1, default=1)
    unit_amount_cents: int = Field(ge=0)


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
    except StudentNotFound as exc:
        raise HTTPException(status_code=404, detail="student not found") from exc

    if student.parent_id != parent_id:
        raise HTTPException(status_code=409, detail="invoice parent must match student parent")

    if enrollment_id is None:
        return

    if not any(session.enrollment_id == enrollment_id for session in student.enrolled_sessions):
        raise HTTPException(status_code=409, detail="invoice enrollment must belong to student")


def _get_ledger_repo(request: Request) -> MongoBillingLedgerRepository:
    return MongoBillingLedgerRepository(request.app.state.db)


def _get_autopay_gateway() -> RealStripeGateway | None:
    s = get_settings()
    if not s.stripe_api_key or not s.stripe_webhook_secret:
        return None
    return RealStripeGateway(api_key=s.stripe_api_key, webhook_secret=s.stripe_webhook_secret)


@router.post(
    "/billing/invoices/{invoice_id}/send",
    response_model=SendInvoiceResponse,
)
async def send_billing_invoice(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
    stripe: RealStripeGateway | None = Depends(_get_autopay_gateway),
) -> SendInvoiceResponse:
    """Send (or re-send) an invoice to the parent.

    - Finalizes draft invoices before sending (draft → open).
    - Records delivery status (delivery axis only — financial status unchanged).
    - Returns a Stripe Checkout URL when a balance is outstanding (stubbed if
      Stripe is not configured in the current environment).
    """
    settings = get_settings()
    frontend_url = (settings.frontend_url or "https://app.example.com").rstrip("/")
    use_case = SendInvoice(
        ledger=ledger,
        stripe=stripe,
        success_url=f"{frontend_url}/parent/payments?invoice=paid",
        cancel_url=f"{frontend_url}/parent/payments?invoice=cancelled",
    )
    try:
        result = await use_case.execute(invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SendInvoiceResponse(
        invoice_id=result.invoice.invoice_id,
        delivery_status=result.invoice.delivery_status,
        sent_at=result.invoice.sent_at,
        last_sent_at=result.invoice.last_sent_at,
        checkout_url=result.checkout_url,
    )


@router.post(
    "/billing/invoices/{invoice_id}/charge-autopay",
    response_model=ChargeAutopayResponse,
)
async def charge_invoice_via_autopay(
    invoice_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
    stripe: RealStripeGateway | None = Depends(_get_autopay_gateway),
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
    if stripe is None:
        raise HTTPException(status_code=503, detail="Stripe autopay not configured")
    use_case = ChargeInvoiceViaAutopay(ledger=ledger, stripe=stripe)
    try:
        result = await use_case.execute(invoice_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return ChargeAutopayResponse(
        invoice_id=result.invoice_id,
        success=result.success,
        status=result.status,
        balance_due_cents=result.balance_due_cents,
        requires_action=result.requires_action,
        decline_code=result.decline_code,
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
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
) -> InvoiceLineResponse:
    use_case = AddInvoiceLine(ledger=ledger)
    try:
        result = await use_case.execute(
            AddInvoiceLineCommand(
                invoice_id=invoice_id,
                description=body.description,
                line_type=body.line_type,
                quantity=body.quantity,
                unit_amount_cents=body.unit_amount_cents,
                product_id=body.product_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    line = result.line
    return InvoiceLineResponse(
        line_id=line.line_id,
        invoice_id=line.invoice_id,
        line_type=line.line_type,
        description=line.description,
        quantity=line.quantity,
        unit_amount_cents=line.unit_amount_cents,
        amount_cents=line.amount_cents,
        invoice_total_cents=result.invoice.total_cents,
        invoice_balance_due_cents=result.invoice.balance_due_cents,
        invoice_status=result.invoice.status,
    )


@router.delete(
    "/billing/invoices/{invoice_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_invoice_line(
    invoice_id: str,
    line_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
) -> None:
    use_case = RemoveInvoiceLine(ledger=ledger)
    try:
        await use_case.execute(RemoveInvoiceLineCommand(invoice_id=invoice_id, line_id=line_id))
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
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
) -> dict[str, bool]:
    from backend.v2.contexts.billing.domain.ledger import void_invoice

    invoice = await ledger.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    if (
        invoice.status in {"partially_paid", "paid"}
        or invoice.balance_due_cents != invoice.total_cents
    ):
        raise HTTPException(
            status_code=409,
            detail="cannot void invoice with recorded payments; issue refund or credit first",
        )
    try:
        voided = void_invoice(invoice, reason=body.reason, now=datetime.now(UTC))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await ledger.save_invoice(voided)
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


@router.post(
    "/billing/invoices/{invoice_id}/record-payment",
    response_model=RecordManualPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_manual_payment(
    invoice_id: str,
    body: RecordManualPaymentRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
) -> RecordManualPaymentResponse:
    """Record a manual payment (cash, check, etc.) against a ledger invoice.

    Creates a LedgerPayment and allocates it to the invoice balance.
    Partial payments are allowed; the invoice status updates accordingly.
    """
    use_case = RecordManualPayment(ledger=ledger)
    try:
        result = await use_case.execute(
            RecordManualPaymentCommand(
                invoice_id=invoice_id,
                amount_cents=body.amount_cents,
                payment_method=body.payment_method,  # type: ignore[arg-type]
                reference_number=body.reference_number,
                notes=body.notes,
            )
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc
    return RecordManualPaymentResponse(
        invoice_id=result.invoice_id,
        payment_id=result.payment_id,
        invoice_status=result.invoice_status,
        balance_due_cents=result.balance_due_cents,
    )


@router.post(
    "/students/{student_id}/invoices",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def create_student_invoice(
    student_id: str,
    body: CreateStudentInvoiceRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
    ledger: MongoBillingLedgerRepository = Depends(_get_ledger_repo),
) -> dict:
    if body.student_id != student_id:
        raise HTTPException(status_code=409, detail="invoice student must match route student")
    await _validate_student_invoice_scope(
        use_cases,
        student_id=student_id,
        parent_id=body.parent_id,
        enrollment_id=body.enrollment_id,
    )
    now = datetime.now(UTC)
    invoice_id = f"inv-{new_ulid()}"
    invoice = LedgerInvoice(
        invoice_id=invoice_id,
        academy_id=claims.academy_id,
        parent_id=body.parent_id,
        student_id=student_id,
        enrollment_id=body.enrollment_id,
        period=body.period,
        status="draft",
        subtotal_cents=0,
        discount_cents=0,
        total_cents=0,
        balance_due_cents=0,
        currency="usd",
        due_date=body.due_date,
        created_at=now,
        updated_at=now,
    )
    idempotency_key = f"admin-invoice-{invoice_id}"
    created = await ledger.create_invoice(invoice, lines=[], idempotency_key=idempotency_key)
    return created.model_dump(mode="json")


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
