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
    """Allocate one Checkout payment across invoices with per-invoice idempotency.

    Any remainder that no invoice can absorb (e.g. every invoice was zeroed by a
    manual payment while an ACH debit was settling — #533) is allocated once more
    against the first invoice under a dedicated idempotency key: the domain caps
    the applied amount at the invoice balance and mints an overpayment credit for
    the rest, so settled money is never left stranded as an unapplied payment.
    """
    remaining = amount_cents
    new_allocations = 0
    sorted_invoices = sorted(invoices, key=lambda item: item.invoice_id)
    for invoice in sorted_invoices:
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
    if remaining > 0 and sorted_invoices:
        overflow_key = f"{allocation_key_prefix}:overpayment"
        existing_overflow = await ledger.get_payment_allocation_by_idempotency_key(overflow_key)
        if existing_overflow is None:
            await ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=sorted_invoices[0].invoice_id,
                amount_cents=remaining,
                idempotency_key=overflow_key,
            )
            new_allocations += 1
    return new_allocations


def _field(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
