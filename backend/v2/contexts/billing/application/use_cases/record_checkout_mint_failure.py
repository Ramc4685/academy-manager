"""Record a pay link that could not be created (issue #426).

Shared by every path that mints a Stripe Checkout session for an invoice —
``SendInvoice`` (admin send / re-send) and the parent portal's "Pay balance"
composition — so a broken payment setup produces the same operator-visible
trail no matter who tripped over it.

Design notes
------------
* Rows land on the existing ``payment_attempts`` collection with the
  ``checkout_mint_failed`` status, which charge-outcome readers filter out
  (see ``domain.payment_attempt_kinds``). No new infrastructure — alerting is
  issue #428, the dedicated admin surface is issue #432.
* One row **per invoice**, carrying that invoice's own ``balance_due_cents``.
  A bundled pay link covering three $100 invoices records 3 x $100, not
  3 x $300 — the reports map this amount into outstanding exposure.
* Idempotent per invoice/period/amount/failure-code, so a parent re-clicking
  "Pay" against a broken Connect account does not spam the collection.
* Best-effort: telemetry must never be the reason a send or a checkout blows
  up. The caller has already logged at ERROR.
"""

from __future__ import annotations

import logging
from typing import Protocol

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    CHECKOUT_MINT_FAILED_STATUS,
)

log = logging.getLogger(__name__)

# Distinct, stable failure codes. Deliberately narrow: an academy that has
# simply never onboarded Stripe Connect is NOT a failure — it is an
# informational academy that collects payment off-platform.
CHECKOUT_FAILURE_STRIPE_ERROR = "checkout_creation_failed"
CHECKOUT_FAILURE_ACCOUNTS_NOT_CONFIGURED = "connected_accounts_not_configured"
CHECKOUT_FAILURE_ACCOUNT_NOT_READY = "connected_account_not_ready"

# Truncation bound for provider error text persisted on the attempt row.
MAX_FAILURE_MESSAGE_CHARS = 500


class _AttemptRecorder(Protocol):
    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict: ...


async def record_checkout_mint_failure(
    ledger: _AttemptRecorder,
    *,
    invoices: list[LedgerInvoice],
    failure_code: str,
    failure_message: str,
) -> None:
    """Record one ``checkout_mint_failed`` attempt row per invoice."""
    message = failure_message[:MAX_FAILURE_MESSAGE_CHARS]
    for invoice in invoices:
        try:
            await ledger.record_payment_attempt(
                invoice_id=invoice.invoice_id,
                parent_id=invoice.parent_id,
                # This invoice's OWN balance, never the bundle total: three
                # $100 invoices behind one broken link are $300 of exposure.
                amount_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                status=CHECKOUT_MINT_FAILED_STATUS,
                stripe_payment_intent_id=None,
                stripe_checkout_session_id=None,
                failure_code=failure_code,
                failure_message=message,
                idempotency_key=(
                    f"invoice-checkout-failure:{invoice.invoice_id}:{invoice.period}:"
                    f"{invoice.balance_due_cents}:{failure_code}"
                ),
                created_by_event_id=None,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.error(
                "record_checkout_mint_failure: could not record attempt invoice=%s err=%s",
                invoice.invoice_id,
                exc,
            )
