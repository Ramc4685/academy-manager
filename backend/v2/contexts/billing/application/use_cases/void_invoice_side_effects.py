"""Unwind everything a voided invoice was still holding (issue #784).

INVARIANT — voiding an invoice means it owes nothing, so nothing may keep
behaving as though it does. Marking the ``LedgerInvoice`` void is only the
first third of that:

1. the ledger row goes ``void`` (the caller does this);
2. any account credit the invoice consumed goes BACK to the family — otherwise
   the credit is spent forever on an invoice that no longer owes anything, and
   the parent's real balance is understated;
3. a Stripe Invoicing invoice linked by ``stripe_invoice_id`` is voided in
   Stripe too — otherwise Stripe keeps dunning the family for, and will happily
   collect, an invoice the academy has written off.

Both void paths (admin ``POST /billing/invoices/{id}/void`` and the
cancel / withdraw / pause lifecycle sync) call :func:`unwind_voided_invoice`.
Adding a third void path without calling it re-opens this defect.

Ordering: this runs AFTER the ledger-side void is committed, the same order
the payment-void path uses. A Stripe outage must not roll back a void the
operator has already been told happened, so the Stripe call is logged and
swallowed — loudly, at error level, with the ids needed to reconcile by hand.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

log = logging.getLogger(__name__)


class VoidCreditsPort(Protocol):
    async def unapply_credits(
        self, *, invoice_id: str, reason: str, now: datetime | None = None
    ) -> int: ...


class VoidStripeInvoicePort(Protocol):
    async def void_stripe_invoice(self, stripe_invoice_id: str) -> None: ...


async def unwind_voided_invoice(
    *,
    invoice_id: str,
    stripe_invoice_id: str | None,
    credits: VoidCreditsPort | None,
    stripe: VoidStripeInvoicePort | None,
    reason: str,
    now: datetime,
) -> int:
    """Restore applied credit and void the Stripe invoice. Returns cents restored.

    Both ports are optional so a composition root that genuinely has neither
    still works, but a root that omits ``credits`` silently re-opens the credit
    half of this bug for its own entry points — wire it.
    """
    restored = 0
    if credits is not None:
        try:
            restored = await credits.unapply_credits(invoice_id=invoice_id, reason=reason, now=now)
        except Exception:
            # The ledger-side void already committed. Losing the credit
            # restoration is a money error an operator has to see.
            log.exception("void_invoice_credit_unapply_failed", extra={"invoice_id": invoice_id})
        else:
            if restored:
                log.info(
                    "void_invoice_credit_restored",
                    extra={"invoice_id": invoice_id, "restored_cents": restored},
                )
    if stripe is not None and stripe_invoice_id:
        try:
            await stripe.void_stripe_invoice(stripe_invoice_id)
        except Exception:
            # Stripe can legitimately refuse (already paid outside our
            # knowledge) or simply be down. Either way the invoice is still
            # collectible in Stripe while we think it is void, so this must be
            # visible rather than swallowed silently.
            log.exception(
                "void_invoice_stripe_void_failed",
                extra={"invoice_id": invoice_id, "stripe_invoice_id": stripe_invoice_id},
            )
    return restored
