from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    RecordManualPayment,
    RecordManualPaymentCommand,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
    allocate_payment_to_invoice,
)

# ---------------------------------------------------------------------------
# In-memory fake ledger for RecordManualPayment tests
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _make_invoice(
    invoice_id: str = "inv-1",
    status: str = "open",
    balance_due_cents: int = 6_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=6_000,
        discount_cents=0,
        total_cents=6_000,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=_NOW,
        updated_at=_NOW,
    )


class _FakeLedger:
    """Minimal in-memory LedgerRepository for use-case unit tests."""

    def __init__(self, invoice: LedgerInvoice | None) -> None:
        self._invoice = invoice
        self.recorded_payment: LedgerPayment | None = None
        self.allocated: dict[str, Any] | None = None

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        if self._invoice and self._invoice.invoice_id == invoice_id:
            return self._invoice
        return None

    async def record_payment(
        self, payment: LedgerPayment, *, idempotency_key: str
    ) -> LedgerPayment:
        self.recorded_payment = payment
        return payment

    async def allocate_payment(
        self, *, payment_id: str, invoice_id: str, amount_cents: int, idempotency_key: str
    ) -> LedgerAllocationResult:
        assert self._invoice is not None
        new_balance = self._invoice.balance_due_cents - amount_cents
        new_status = "paid" if new_balance == 0 else "partially_paid"
        updated_invoice = self._invoice.model_copy(
            update={"balance_due_cents": new_balance, "status": new_status}
        )
        self.allocated = {"payment_id": payment_id, "amount_cents": amount_cents}
        dummy_payment = LedgerPayment(
            payment_id=payment_id,
            academy_id="acad-1",
            parent_id="parent-1",
            amount_cents=amount_cents,
            unapplied_amount_cents=0,
            currency="usd",
            status="succeeded",
            created_at=_NOW,
            updated_at=_NOW,
        )
        dummy_allocation = PaymentAllocation(
            allocation_id="alloc-x",
            academy_id="acad-1",
            payment_id=payment_id,
            invoice_id=invoice_id,
            amount_cents=amount_cents,
            created_at=_NOW,
        )
        return LedgerAllocationResult(
            invoice=updated_invoice,
            payment=dummy_payment,
            allocation=dummy_allocation,
        )

    async def get_open_invoice_for_student(self, student_id: str, period: str) -> LedgerInvoice | None:
        return None

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        return invoice


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


# ---------------------------------------------------------------------------
# RecordManualPayment use-case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_manual_payment_full_pay_marks_invoice_paid() -> None:
    ledger = _FakeLedger(_make_invoice(balance_due_cents=6_000))
    uc = RecordManualPayment(ledger=ledger, clock=lambda: _NOW)
    result = await uc.execute(
        RecordManualPaymentCommand(invoice_id="inv-1", amount_cents=6_000, payment_method="cash")
    )
    assert result.invoice_status == "paid"
    assert result.balance_due_cents == 0
    assert ledger.recorded_payment is not None
    assert ledger.recorded_payment.amount_cents == 6_000
    assert ledger.recorded_payment.payment_method == "cash"
    assert ledger.recorded_payment.status == "succeeded"


@pytest.mark.asyncio
async def test_record_manual_payment_partial_leaves_partially_paid() -> None:
    ledger = _FakeLedger(_make_invoice(balance_due_cents=6_000))
    uc = RecordManualPayment(ledger=ledger, clock=lambda: _NOW)
    result = await uc.execute(
        RecordManualPaymentCommand(invoice_id="inv-1", amount_cents=2_000, payment_method="check")
    )
    assert result.invoice_status == "partially_paid"
    assert result.balance_due_cents == 4_000
    assert ledger.allocated is not None
    assert ledger.allocated["amount_cents"] == 2_000


@pytest.mark.asyncio
async def test_record_manual_payment_raises_if_invoice_not_found() -> None:
    ledger = _FakeLedger(None)
    uc = RecordManualPayment(ledger=ledger)
    with pytest.raises(ValueError, match="not found"):
        await uc.execute(
            RecordManualPaymentCommand(invoice_id="inv-missing", amount_cents=100)
        )


@pytest.mark.asyncio
async def test_record_manual_payment_raises_if_invoice_already_paid() -> None:
    ledger = _FakeLedger(_make_invoice(status="paid", balance_due_cents=0))
    uc = RecordManualPayment(ledger=ledger)
    with pytest.raises(ValueError, match="not payable"):
        await uc.execute(
            RecordManualPaymentCommand(invoice_id="inv-1", amount_cents=100)
        )


@pytest.mark.asyncio
async def test_record_manual_payment_raises_if_amount_exceeds_balance() -> None:
    ledger = _FakeLedger(_make_invoice(balance_due_cents=6_000))
    uc = RecordManualPayment(ledger=ledger)
    with pytest.raises(ValueError, match="exceeds balance_due_cents"):
        await uc.execute(
            RecordManualPaymentCommand(invoice_id="inv-1", amount_cents=9_999)
        )
