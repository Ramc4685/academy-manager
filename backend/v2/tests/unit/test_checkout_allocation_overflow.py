"""Unit tests for the #533 overflow arm of allocate_checkout_payment_across_invoices.

The overflow arm is best-effort: if the domain raises because the payment's
unapplied balance was already consumed under a different idempotency-key prefix,
the helper must log and return (pre-#533 behavior) instead of propagating — a
raise here would send an otherwise-handled webhook event into retry/quarantine.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.checkout_allocation import (
    allocate_checkout_payment_across_invoices,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment

_NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


def _invoice(invoice_id: str, balance_due_cents: int) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        period="2026-06",
        status="paid" if balance_due_cents == 0 else "open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payment(unapplied_cents: int) -> LedgerPayment:
    return LedgerPayment(
        payment_id="pay-1",
        academy_id="acad-1",
        parent_id="parent-1",
        amount_cents=10_000,
        unapplied_amount_cents=unapplied_cents,
        currency="usd",
        status="succeeded",
        created_at=_NOW,
        updated_at=_NOW,
    )


class _RaisingLedger:
    """Fake ledger with no prior allocations whose allocate_payment raises the
    domain error for a payment with no usable money left."""

    def __init__(self) -> None:
        self.allocate_calls: list[dict[str, Any]] = []

    async def get_payment_allocation_by_idempotency_key(self, key: str) -> None:
        return None

    async def allocate_payment(self, **kwargs: Any) -> Any:
        self.allocate_calls.append(kwargs)
        raise ValueError("no payable invoice balance or payment amount")


@pytest.mark.asyncio
async def test_overflow_arm_tolerates_consumed_unapplied_balance(caplog) -> None:
    """Payment balance already consumed under another key prefix: the overflow
    allocation raises inside the ledger, and the helper logs + returns instead
    of propagating (which would quarantine the webhook event)."""
    ledger = _RaisingLedger()
    with caplog.at_level("WARNING"):
        allocated = await allocate_checkout_payment_across_invoices(
            ledger=ledger,
            payment=_payment(unapplied_cents=0),
            invoices=[_invoice("inv-1", balance_due_cents=0)],
            amount_cents=10_000,
            allocation_key_prefix="invoice-checkout-alloc:cs_x",
        )
    assert allocated == 0
    # Only the overflow arm attempted an allocation (the per-invoice loop skips
    # the zero-balance invoice), and its failure was swallowed with a warning.
    assert len(ledger.allocate_calls) == 1
    assert ledger.allocate_calls[0]["idempotency_key"] == "invoice-checkout-alloc:cs_x:overpayment"
    assert any("leaving it" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_per_invoice_loop_errors_still_propagate() -> None:
    """Only the overflow arm is tolerant: a raise from a per-invoice allocation
    (positive balance) still propagates."""
    ledger = _RaisingLedger()
    with pytest.raises(ValueError):
        await allocate_checkout_payment_across_invoices(
            ledger=ledger,
            payment=_payment(unapplied_cents=10_000),
            invoices=[_invoice("inv-1", balance_due_cents=10_000)],
            amount_cents=10_000,
            allocation_key_prefix="invoice-checkout-alloc:cs_y",
        )
    assert len(ledger.allocate_calls) == 1
    assert ledger.allocate_calls[0]["idempotency_key"] == "invoice-checkout-alloc:cs_y:inv-1"
