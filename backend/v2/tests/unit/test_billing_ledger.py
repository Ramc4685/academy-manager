from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
    allocate_payment_to_invoice,
)


def test_partial_payment_reduces_invoice_balance_without_credit() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id="inv-1",
        academy_id="academy-1",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 10),
        created_at=now,
        updated_at=now,
    )
    payment = LedgerPayment(
        payment_id="pay-1",
        academy_id="academy-1",
        parent_id="parent-1",
        amount_cents=4_000,
        unapplied_amount_cents=4_000,
        currency="usd",
        status="succeeded",
        payment_method="cash",
        paid_at=now,
        created_at=now,
        updated_at=now,
    )
    line = InvoiceLine(
        line_id="line-1",
        academy_id="academy-1",
        invoice_id="inv-1",
        line_type="tuition",
        description="June tuition",
        quantity=1,
        unit_amount_cents=10_000,
        amount_cents=10_000,
        source_type="enrollment",
        source_id="enroll-1",
        created_at=now,
    )

    result = allocate_payment_to_invoice(
        invoice=invoice,
        payment=payment,
        lines=[line],
        requested_amount_cents=4_000,
        allocation_id="alloc-1",
        now=now,
    )

    assert result.invoice.balance_due_cents == 6_000
    assert result.invoice.status == "partially_paid"
    assert result.payment.unapplied_amount_cents == 0
    assert result.allocation.amount_cents == 4_000
    assert result.overpayment_credit is None


def test_overpayment_allocates_invoice_balance_and_returns_credit() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id="inv-2",
        academy_id="academy-1",
        parent_id="parent-1",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 10),
        created_at=now,
        updated_at=now,
    )
    payment = LedgerPayment(
        payment_id="pay-2",
        academy_id="academy-1",
        parent_id="parent-1",
        amount_cents=12_000,
        unapplied_amount_cents=12_000,
        currency="usd",
        status="succeeded",
        payment_method="zelle",
        paid_at=now,
        created_at=now,
        updated_at=now,
    )

    result = allocate_payment_to_invoice(
        invoice=invoice,
        payment=payment,
        lines=[],
        requested_amount_cents=12_000,
        allocation_id="alloc-2",
        now=now,
    )

    assert result.allocation.amount_cents == 10_000
    assert result.invoice.balance_due_cents == 0
    assert result.invoice.status == "paid"
    assert result.payment.unapplied_amount_cents == 0
    assert result.overpayment_credit is not None
    assert result.overpayment_credit.amount_cents == 2_000
    assert result.overpayment_credit.remaining_amount_cents == 2_000
