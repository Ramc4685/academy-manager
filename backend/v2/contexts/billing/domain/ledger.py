"""Billing ledger domain objects.

The ledger separates invoice truth from payment truth. Payments can be
allocated partially, and any overpayment becomes an account credit entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry

InvoiceStatus = Literal["draft", "open", "partially_paid", "paid", "void"]
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
    stripe_invoice_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    # delivery tracking (separate axis from financial status)
    delivery_status: Literal["not_sent", "sent", "delivery_failed"] = "not_sent"
    sent_at: datetime | None = None
    last_sent_at: datetime | None = None
    # audit
    finalized_at: datetime | None = None
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
    stripe_invoice_id: str | None = None
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


def recompute_totals(invoice: LedgerInvoice, lines: list[InvoiceLine]) -> LedgerInvoice:
    """Derive subtotal/total/balance_due from lines. Callers never set totals directly."""
    subtotal = sum(line.amount_cents for line in lines)
    total = max(0, subtotal - invoice.discount_cents)
    # NOTE: `allocated` is inferred from persisted totals (total_cents - balance_due_cents),
    # not from summing payment_allocations. This is correct under a single-writer model.
    # Under concurrent writes to the same invoice, the second writer's recompute will see
    # a stale baseline. Phase 3 should either add optimistic locking (e.g. a `version` field)
    # or derive allocated from the payment_allocations collection directly.
    allocated = invoice.total_cents - invoice.balance_due_cents  # already-allocated amount
    balance = max(0, total - allocated)
    new_status = invoice.status
    if invoice.status not in ("draft", "void"):
        if balance == 0:
            new_status = "paid"
        elif balance < total:
            new_status = "partially_paid"
        else:
            new_status = "open"
    return invoice.model_copy(
        update={
            "subtotal_cents": subtotal,
            "total_cents": total,
            "balance_due_cents": balance,
            "status": new_status,
        }
    )


def add_line(
    invoice: LedgerInvoice,
    lines: list[InvoiceLine],
    new_line: InvoiceLine,
    *,
    now: datetime,
) -> tuple[LedgerInvoice, list[InvoiceLine]]:
    """Append a line and recompute totals. Enforces edit rules."""
    if invoice.status in ("paid", "void"):
        raise ValueError(f"cannot add lines to a {invoice.status} invoice")
    updated_lines = [*lines, new_line]
    updated_invoice = recompute_totals(
        invoice.model_copy(update={"updated_at": now}), updated_lines
    )
    return updated_invoice, updated_lines


def finalize(invoice: LedgerInvoice, *, now: datetime) -> LedgerInvoice:
    """Transition draft → open. Monthly invoices are created directly as open (no draft step)."""
    if invoice.status != "draft":
        raise ValueError(f"can only finalize a draft invoice, got {invoice.status}")
    return invoice.model_copy(
        update={
            "status": "open",
            "finalized_at": now,
            "updated_at": now,
        }
    )


def void_invoice(invoice: LedgerInvoice, *, reason: str, now: datetime) -> LedgerInvoice:
    """Transition draft/open/partially_paid → void. Paid invoices cannot be voided."""
    if invoice.status == "paid":
        raise ValueError("paid invoices cannot be voided; use refund/credit instead")
    if invoice.status == "void":
        raise ValueError("invoice is already void")
    return invoice.model_copy(
        update={
            "status": "void",
            "updated_at": now,
        }
    )


def record_delivery(
    invoice: LedgerInvoice,
    *,
    outcome: Literal["sent", "delivery_failed"],
    now: datetime,
) -> LedgerInvoice:
    """Update delivery tracking only. Financial status is never changed by this op."""
    if invoice.status == "draft":
        raise ValueError("cannot record delivery on a draft invoice")
    updates: dict = {
        "delivery_status": outcome,
        "last_sent_at": now,
        "updated_at": now,
    }
    if outcome == "sent" and invoice.sent_at is None:
        updates["sent_at"] = now
    return invoice.model_copy(update=updates)


# --- Domain events ---


@dataclass(frozen=True)
class InvoiceLineAdded:
    invoice_id: str
    line_id: str
    academy_id: str


@dataclass(frozen=True)
class InvoiceFinalized:
    invoice_id: str
    academy_id: str
    finalized_at: datetime


@dataclass(frozen=True)
class InvoiceVoided:
    invoice_id: str
    academy_id: str
    reason: str


@dataclass(frozen=True)
class InvoiceDelivered:
    invoice_id: str
    academy_id: str
    outcome: str
    delivered_at: datetime
