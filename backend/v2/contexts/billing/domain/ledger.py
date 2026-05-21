"""Billing ledger domain objects.

The ledger separates invoice truth from payment truth. Payments can be
allocated partially, and any overpayment becomes an account credit entry.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry

InvoiceStatus = Literal["open", "partially_paid", "paid", "void"]
LedgerPaymentStatus = Literal["pending", "succeeded", "failed", "refunded"]


class LedgerInvoice(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    academy_id: str
    parent_id: str
    student_id: str | None = None
    enrollment_id: str | None = None
    period: str
    status: InvoiceStatus = "open"
    subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(default=0, ge=0)
    total_cents: int = Field(ge=0)
    balance_due_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    due_date: date
    pdf_artifact_id: str | None = None
    created_at: datetime
    updated_at: datetime


class InvoiceLine(BaseModel):
    model_config = {"frozen": True}

    line_id: str
    academy_id: str
    invoice_id: str
    line_type: str
    description: str
    quantity: int = Field(ge=1)
    unit_amount_cents: int
    amount_cents: int
    source_type: str | None = None
    source_id: str | None = None
    created_at: datetime


class LedgerPayment(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    academy_id: str
    parent_id: str
    amount_cents: int = Field(ge=0)
    unapplied_amount_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    status: LedgerPaymentStatus = "pending"
    payment_method: str | None = None
    stripe_payment_intent_id: str | None = None
    paid_at: datetime | None = None
    recorded_by: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PaymentAllocation(BaseModel):
    model_config = {"frozen": True}

    allocation_id: str
    academy_id: str
    payment_id: str
    invoice_id: str
    amount_cents: int = Field(ge=0)
    created_at: datetime


class LedgerAllocationResult(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice
    payment: LedgerPayment
    allocation: PaymentAllocation
    overpayment_credit: CreditLedgerEntry | None = None


def allocate_payment_to_invoice(
    *,
    invoice: LedgerInvoice,
    payment: LedgerPayment,
    lines: list[InvoiceLine],
    requested_amount_cents: int,
    allocation_id: str,
    now: datetime,
) -> LedgerAllocationResult:
    """Apply a payment to an invoice without mutating the inputs."""
    if invoice.academy_id != payment.academy_id:
        raise ValueError("invoice and payment belong to different academies")
    if invoice.parent_id != payment.parent_id:
        raise ValueError("invoice and payment belong to different parents")
    if requested_amount_cents <= 0:
        raise ValueError("allocation amount must be positive")
    if invoice.status == "void":
        raise ValueError("void invoices cannot receive payments")

    usable_from_payment = min(requested_amount_cents, payment.unapplied_amount_cents)
    allocated_cents = min(usable_from_payment, invoice.balance_due_cents)
    if allocated_cents <= 0:
        raise ValueError("no payable invoice balance or payment amount")

    overpayment_cents = usable_from_payment - allocated_cents
    new_balance = invoice.balance_due_cents - allocated_cents
    if new_balance == 0:
        new_status: InvoiceStatus = "paid"
    elif new_balance < invoice.total_cents:
        new_status = "partially_paid"
    else:
        new_status = "open"

    allocation = PaymentAllocation(
        allocation_id=allocation_id,
        academy_id=invoice.academy_id,
        payment_id=payment.payment_id,
        invoice_id=invoice.invoice_id,
        amount_cents=allocated_cents,
        created_at=now,
    )
    updated_invoice = invoice.model_copy(
        update={
            "balance_due_cents": new_balance,
            "status": new_status,
            "updated_at": now,
        }
    )
    updated_payment = payment.model_copy(
        update={
            "unapplied_amount_cents": payment.unapplied_amount_cents - usable_from_payment,
            "updated_at": now,
        }
    )
    credit = None
    if overpayment_cents > 0:
        credit = CreditLedgerEntry(
            credit_id=f"credit-{allocation_id}",
            academy_id=invoice.academy_id,
            parent_id=invoice.parent_id,
            student_id=invoice.student_id,
            enrollment_id=invoice.enrollment_id,
            invoice_id=invoice.invoice_id,
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=overpayment_cents,
            remaining_amount_cents=overpayment_cents,
            currency=invoice.currency,
            reason=f"Overpayment on invoice {invoice.invoice_id}",
            source_type="OVERPAYMENT",
            source_id=allocation_id,
            created_at=now,
            updated_at=now,
        )
    return LedgerAllocationResult(
        invoice=updated_invoice,
        payment=updated_payment,
        allocation=allocation,
        overpayment_credit=credit,
    )
