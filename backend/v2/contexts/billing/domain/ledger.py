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
LedgerPaymentStatus = Literal["pending", "succeeded", "failed", "refunded", "partially_refunded"]


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
    # cumulative amount refunded against this invoice; single source of truth, written only
    # by MongoBillingLedgerRepository.apply_invoice_refund
    refunded_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    due_date: date
    # Human-facing invoice number, e.g. "BLNO-202606-001". Minted once at invoice-creation
    # time via MongoBillingCounterRepository (atomic per academy+month counter) — see
    # format_invoice_number() below. None for invoices created before Slice D (not
    # backfilled; see migration 0138 docstring for the backfill decision). Gaps in the
    # sequence ARE allowed: a voided/failed invoice still consumes a counter value, and
    # that number is never reused or reassigned. This is intentional — gapless numbering
    # would require serializing invoice creation across the whole academy+month, which is
    # unnecessary for this use case (unlike, say, government-mandated sequential invoicing).
    invoice_number: str | None = None
    pdf_artifact_id: str | None = None
    stripe_invoice_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    # delivery tracking (separate axis from financial status)
    delivery_status: Literal["not_sent", "sent", "delivery_failed"] = "not_sent"
    sent_at: datetime | None = None
    last_sent_at: datetime | None = None
    # Resend provider message id from the most recent successful send. Lets the
    # admin panel deep-link to the Resend record (open/click/bounce lives only
    # in the Resend dashboard). Only overwritten on a successful send; a later
    # delivery_failed leaves the last good id in place so the link still works.
    email_provider_message_id: str | None = None
    # In-flight Stripe Checkout Session for this invoice. Set while a parent is paying
    # manually, cleared by the session's terminal webhook. Autopay refuses to charge a
    # held invoice so a manual payment and a dunning tick cannot both collect the same
    # balance — see contexts.billing.domain.checkout_hold.
    checkout_hold_session_id: str | None = None
    checkout_hold_started_at: datetime | None = None
    # audit
    finalized_at: datetime | None = None
    # Why/when the invoice was voided (issue #651): "admin_void", or the
    # enrollment transition ("enrollment_cancelled", "enrollment_paused", ...).
    void_reason: str | None = None
    voided_at: datetime | None = None
    # optimistic-concurrency token; bumped by the repository on each persisted write
    version: int = Field(default=0, ge=0)
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
    category: str | None = None
    category_label: str | None = None
    discount_kind: str | None = None
    gross_cents: int | None = None
    net_cents: int | None = None
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
    refunded_cents: int = Field(default=0, ge=0)
    payment_method: str | None = None
    stripe_payment_intent_id: str | None = None
    stripe_invoice_id: str | None = None
    paid_at: datetime | None = None
    recorded_by: str | None = None
    notes: str | None = None
    metadata: dict[str, str] | None = None
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


def format_invoice_number(*, prefix: str, yyyymm: str, seq: int) -> str:
    """Format a human-facing invoice number: ``{prefix}-{YYYY}-{MM}-{seq:04d}``.

    Owner decision 2026-09-12 (issue #659): the tuition month must be readable
    at a glance, so the period is split (``BLNO-2026-09-0042``) rather than run
    together as ``BLNO-202609-042`` — parents read the dashed form as a date.

    Pure formatting only — the caller supplies the already-minted, race-safe
    sequence value (from ``MongoBillingCounterRepository.next_value``) and the
    tenant's configured prefix (from ``BillingSettings.invoice_number_prefix``).
    ``seq`` is zero-padded to 4 digits but never truncated: sequences beyond
    9999 simply widen the field (e.g. ``BLNO-2026-06-12345``) rather than
    wrapping or colliding with an earlier number.
    """
    if not prefix:
        raise ValueError("prefix must not be blank")
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        raise ValueError("yyyymm must be 6 digits (YYYYMM)")
    if seq <= 0:
        raise ValueError("seq must be positive")
    return f"{prefix}-{yyyymm[:4]}-{yyyymm[4:]}-{seq:04d}"


#: Month names, indexed 1-12. Spelled out rather than taken from ``strftime``
#: so the rendering never depends on the process locale — a parent-facing
#: email must say "September 2026" on every host.
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_tuition_month(period: str) -> str:
    """Render a ``YYYY-MM`` billing period as ``"September 2026"`` (issue #659).

    Every parent-facing surface says which month's tuition it is, in words: the
    2026-09-05 incident was nine families reading "$70.00 ... for 2026-09" as a
    duplicate of the August charge they had just paid. An unparseable period
    degrades to the raw string rather than raising — a malformed period must
    never be the reason a parent's invoice is not delivered.
    """
    text = (period or "").strip()
    year, _, month = text.partition("-")
    if len(year) == 4 and year.isdigit() and len(month) == 2 and month.isdigit():
        index = int(month)
        if 1 <= index <= 12:
            return f"{_MONTH_NAMES[index - 1]} {year}"
    return text


def format_charge_date(value: date) -> str:
    """Render a charge date as ``"September 3"`` (issue #659).

    Spelled from ``_MONTH_NAMES`` rather than ``strftime`` for the same reason
    ``format_tuition_month`` is: a parent-facing email must read the same on
    every host regardless of the process locale. The year is omitted on
    purpose — this only ever renders a charge inside the last 45 days.
    """
    return f"{_MONTH_NAMES[value.month - 1]} {value.day}"


def format_session_label(
    *,
    name: str | None,
    days_of_week: list[str] | tuple[str, ...] | None = None,
    start_time: str | None = None,
) -> str | None:
    """A compact class label for emails, e.g. ``"Mon/Wed 18:00 Junior Badminton"``.

    Two children in one family are billed separately (issue #659: a parent paid
    $120 for one child and was auto-charged $70 for the other on the same
    weekend); naming the class is what lets them tell the two invoices apart.
    Returns ``None`` when there is nothing worth showing.
    """
    days = "/".join(str(d).strip() for d in (days_of_week or []) if str(d).strip())
    parts = [part for part in (days, (start_time or "").strip(), (name or "").strip()) if part]
    return " ".join(parts) or None


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
    if usable_from_payment <= 0:
        raise ValueError("no payable invoice balance or payment amount")
    allocated_cents = max(0, min(usable_from_payment, invoice.balance_due_cents))

    # Zero-balance invoice with real money in hand (e.g. an ACH autopay debit that
    # settles days after an admin recorded a manual payment on the same invoice):
    # instead of raising — which stranded the settled funds as a permanently
    # unapplied ledger payment in webhook quarantine (#533) — the full usable
    # amount becomes an overpayment credit and the invoice is left untouched.
    overpayment_cents = usable_from_payment - allocated_cents
    new_balance = invoice.balance_due_cents - allocated_cents
    if allocated_cents == 0:
        new_status: InvoiceStatus = invoice.status
    elif new_balance == 0:
        new_status = "paid"
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


def recompute_totals(
    invoice: LedgerInvoice,
    lines: list[InvoiceLine],
    *,
    allocated_cents: int | None = None,
) -> LedgerInvoice:
    """Derive subtotal/total/balance_due from lines. Callers never set totals directly.

    When ``allocated_cents`` is supplied (the summed ``payment_allocations`` for this invoice),
    the balance is derived from it directly — the correct, concurrency-safe source of truth.
    When omitted, it falls back to inferring ``total_cents - balance_due_cents`` from the
    passed invoice (only safe under a single writer; persistence guards concurrency via the
    invoice ``version`` token).
    """
    subtotal = sum(line.amount_cents for line in lines)
    total = max(0, subtotal - invoice.discount_cents)
    if allocated_cents is None:
        allocated = invoice.total_cents - invoice.balance_due_cents  # already-allocated amount
    else:
        allocated = max(0, allocated_cents)
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
    allocated_cents: int | None = None,
) -> tuple[LedgerInvoice, list[InvoiceLine]]:
    """Append a line and recompute totals. Enforces edit rules.

    ``allocated_cents`` (the summed payment allocations for this invoice) should be passed
    by callers that have it, so the recomputed balance is derived from real allocations
    rather than the possibly-stale invoice projection.
    """
    if invoice.status in ("paid", "void"):
        raise ValueError(f"cannot add lines to a {invoice.status} invoice")
    updated_lines = [*lines, new_line]
    updated_invoice = recompute_totals(
        invoice.model_copy(update={"updated_at": now}),
        updated_lines,
        allocated_cents=allocated_cents,
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
            "void_reason": reason,
            "voided_at": now,
            "updated_at": now,
        }
    )


def record_delivery(
    invoice: LedgerInvoice,
    *,
    outcome: Literal["sent", "delivery_failed"],
    now: datetime,
    provider_message_id: str | None = None,
) -> LedgerInvoice:
    """Update delivery tracking only. Financial status is never changed by this op.

    ``provider_message_id`` is the id the email provider (Resend) returns for a
    successful send. It is only stored on a ``sent`` outcome and only when a
    non-empty id is supplied — a failed send, or a send by a provider that does
    not return an id, leaves any previously stored id untouched.
    """
    if invoice.status == "draft":
        raise ValueError("cannot record delivery on a draft invoice")
    updates: dict = {
        "delivery_status": outcome,
        "last_sent_at": now,
        "updated_at": now,
    }
    if outcome == "sent" and invoice.sent_at is None:
        updates["sent_at"] = now
    if outcome == "sent" and provider_message_id:
        updates["email_provider_message_id"] = provider_message_id
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
