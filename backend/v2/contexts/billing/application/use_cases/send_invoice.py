"""SendInvoice use case — finalize if draft, generate pay link, send email.

Delivery axis invariant: financial status is NEVER changed by this use case.
Only a successful email delivery can set `delivery_status="sent"`.

Calling flow
------------
1. Load invoice by invoice_id (raises ValueError if not found).
2. If status == "draft": call finalize() → save. Financial status becomes "open".
3. If balance_due_cents > 0: create a Stripe Checkout Session for the balance.
4. Send email to parent with the pay link via EmailSendPort when configured.
5. Record delivery only after email succeeds; record delivery_failed after email errors.
6. Return SendInvoiceResult(invoice=updated, checkout_url=str|None).

Re-send: if email succeeds and delivery_status == "sent" already, last_sent_at
updates and sent_at stays the same (domain rule enforced by record_delivery).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import (
    LedgerInvoice,
    finalize,
    record_delivery,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimal ports used by this use case only
# ---------------------------------------------------------------------------


class InvoiceStripeGateway(Protocol):
    """Narrow port — only the checkout-session creation this use case needs."""

    async def create_invoice_checkout_session(
        self,
        *,
        invoice_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, checkout_url)."""
        ...


class InvoiceEmailPort(Protocol):
    """Narrow port for sending an invoice email to a parent."""

    async def send_invoice_email(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        total_cents: int,
        balance_due_cents: int,
        currency: str,
        checkout_url: str | None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class SendInvoiceResult(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice
    checkout_url: str | None = None


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class SendInvoice:
    """Send an invoice to the parent and update delivery tracking."""

    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        stripe: InvoiceStripeGateway | None = None,
        email: InvoiceEmailPort | None = None,
        success_url: str = "https://app.example.com/pay/success",
        cancel_url: str = "https://app.example.com/pay/cancel",
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._stripe = stripe
        self._email = email
        self._success_url = success_url
        self._cancel_url = cancel_url
        self._now = clock

    async def execute(self, invoice_id: str) -> SendInvoiceResult:
        now = self._now()

        # 1. Load invoice
        invoice = await self._ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {invoice_id!r} not found")

        # 2. Finalize draft invoices before sending
        if invoice.status == "draft":
            invoice = finalize(invoice, now=now)
            invoice = await self._ledger.save_invoice(invoice)
            log.info("send_invoice: finalized draft invoice=%s", invoice_id)

        # 3. Generate Stripe Checkout Session for unpaid balance
        checkout_url: str | None = None
        if invoice.balance_due_cents > 0 and self._stripe is not None:
            try:
                _session_id, checkout_url = await self._stripe.create_invoice_checkout_session(
                    invoice_id=invoice_id,
                    amount_cents=invoice.balance_due_cents,
                    currency=invoice.currency,
                    success_url=self._success_url,
                    cancel_url=self._cancel_url,
                    metadata={
                        "invoice_id": invoice_id,
                        "source": "invoice_pay_link",
                        "academy_id": invoice.academy_id,
                        "parent_id": invoice.parent_id,
                    },
                )
                log.info(
                    "send_invoice: checkout_session created invoice=%s url=%s",
                    invoice_id,
                    checkout_url,
                )
            except Exception as exc:
                log.warning(
                    "send_invoice: stripe checkout creation failed invoice=%s err=%s",
                    invoice_id,
                    exc,
                )
                checkout_url = None
        elif invoice.balance_due_cents == 0:
            log.info("send_invoice: invoice=%s already paid — skipping Stripe", invoice_id)
        else:
            log.info(
                "send_invoice: stripe gateway not configured — skipping checkout for invoice=%s",
                invoice_id,
            )

        # 4. Send email and only then record delivery.
        if self._email is not None:
            try:
                await self._email.send_invoice_email(
                    parent_id=invoice.parent_id,
                    invoice_id=invoice_id,
                    period=invoice.period,
                    total_cents=invoice.total_cents,
                    balance_due_cents=invoice.balance_due_cents,
                    currency=invoice.currency,
                    checkout_url=checkout_url,
                )
                invoice = record_delivery(invoice, outcome="sent", now=now)
                invoice = await self._ledger.save_invoice(invoice)
                log.info("send_invoice: email sent for invoice=%s", invoice_id)
            except Exception as exc:
                invoice = record_delivery(invoice, outcome="delivery_failed", now=now)
                invoice = await self._ledger.save_invoice(invoice)
                log.warning(
                    "send_invoice: email failed invoice=%s err=%s — continuing",
                    invoice_id,
                    exc,
                )
        else:
            log.info(
                "send_invoice: email port not configured — skipping email for invoice=%s",
                invoice_id,
            )

        return SendInvoiceResult(invoice=invoice, checkout_url=checkout_url)
