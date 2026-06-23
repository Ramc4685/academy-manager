"""Shared allocation helpers for Stripe Checkout invoice payments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment


async def allocate_checkout_payment_across_invoices(
    *,
    ledger: LedgerRepository,
    payment: LedgerPayment,
    invoices: Iterable[LedgerInvoice],
    amount_cents: int,
    allocation_key_prefix: str,
    conflict_error: type[Exception] = ValueError,
) -> int:
    """Allocate one Checkout payment across invoices with per-invoice idempotency."""
    remaining = amount_cents
    new_allocations = 0
    for invoice in sorted(invoices, key=lambda item: item.invoice_id):
        allocation_key = f"{allocation_key_prefix}:{invoice.invoice_id}"
        existing_allocation = await ledger.get_payment_allocation_by_idempotency_key(allocation_key)
        if existing_allocation is not None:
            if _field(existing_allocation, "invoice_id") != invoice.invoice_id:
                raise conflict_error(
                    "duplicate Stripe obligation: Checkout payment already allocated "
                    f"to {_field(existing_allocation, 'invoice_id')}"
                )
            remaining -= int(_field(existing_allocation, "amount_cents") or 0)
            continue
        if remaining <= 0:
            break
        allocation_amount = min(remaining, max(invoice.balance_due_cents, 0))
        if allocation_amount <= 0:
            continue
        await ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=allocation_amount,
            idempotency_key=allocation_key,
        )
        remaining -= allocation_amount
        new_allocations += 1
    return new_allocations


def _field(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
