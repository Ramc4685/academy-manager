"""ChargeInvoiceViaAutopay — off-session PaymentIntent against saved card for invoice balance.

Financial status invariant: this use case ONLY changes financial status when the PI
succeeds immediately. On decline the invoice stays open/partially_paid. The delivery
axis (sent_at, delivery_status) is never touched here.

Idempotency key ``autopay-{invoice_id}`` on the PI prevents double-charging on retry.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerPayment

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Narrow port — only what this use case needs from Stripe
# ---------------------------------------------------------------------------


class AutopayStripeGateway(Protocol):
    """Narrow port for off-session autopay charge.

    Implementors must:
    1. Retrieve the Stripe Customer for the parent and its default PM.
    2. Create a PaymentIntent with off_session=True, confirm=True.
    3. Return (pi_id, pi_status, decline_code_or_None).

    ``pi_status`` is the raw Stripe PI status string:
    "succeeded", "requires_action", "requires_payment_method", etc.
    ``decline_code`` is set on hard declines (card_declined, etc.).
    """

    async def get_default_payment_method(self, *, parent_id: str) -> tuple[str, str] | None:
        """Return (stripe_customer_id, payment_method_id) or None if no saved card."""
        ...

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, str],
    ) -> tuple[str, str, str | None]:
        """Return (pi_id, pi_status, decline_code_or_None)."""
        ...


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class ChargeResult(BaseModel):
    model_config = {"frozen": True}

    success: bool
    invoice_id: str
    status: str  # invoice status after the attempt
    balance_due_cents: int
    requires_action: bool = False
    decline_code: str | None = None


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------

_CHARGEABLE_STATUSES = frozenset({"open", "partially_paid"})


class ChargeInvoiceViaAutopay:
    """Charge an invoice balance via an off-session Stripe PaymentIntent.

    Inject ``stripe=None`` to run in environments without Stripe configured
    (the use case raises ValueError for un-chargeable invariants before the
    gateway call, so unit tests still exercise all guard logic).
    """

    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        stripe: AutopayStripeGateway | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._stripe = stripe
        self._now = clock

    async def execute(self, invoice_id: str) -> ChargeResult:
        now = self._now()

        # 1. Load invoice
        invoice = await self._ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {invoice_id!r} not found")

        # 2. Guard: invoice must be chargeable
        if invoice.status not in _CHARGEABLE_STATUSES:
            raise ValueError(
                f"invoice {invoice_id!r} is not chargeable (status={invoice.status!r}); "
                f"only {sorted(_CHARGEABLE_STATUSES)} are allowed"
            )
        if invoice.balance_due_cents <= 0:
            raise ValueError(f"invoice {invoice_id!r} has no balance due (balance_due_cents=0)")

        # 3. Look up parent's saved Stripe card
        if self._stripe is None:
            log.info(
                "charge_autopay: stripe gateway not configured — skipping PI creation invoice=%s",
                invoice_id,
            )
            return ChargeResult(
                success=False,
                invoice_id=invoice_id,
                status=invoice.status,
                balance_due_cents=invoice.balance_due_cents,
                decline_code="stripe_not_configured",
            )

        saved = await self._stripe.get_default_payment_method(parent_id=invoice.parent_id)
        if saved is None:
            raise ValueError(
                f"no_saved_payment_method: parent {invoice.parent_id!r} has no saved Stripe card"
            )
        customer_id, pm_id = saved

        # 4. Create off-session PaymentIntent (idempotency key prevents double-charge)
        idempotency_key = f"autopay-{invoice.invoice_id}"
        try:
            pi_id, pi_status, decline_code = await self._stripe.create_off_session_payment_intent(
                amount_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                customer_id=customer_id,
                payment_method_id=pm_id,
                idempotency_key=idempotency_key,
                metadata={
                    "invoice_id": invoice.invoice_id,
                    "academy_id": invoice.academy_id,
                    "source": "autopay",
                },
            )
        except Exception as exc:
            # Stripe card decline or API error — do NOT change invoice status
            decline_str = str(exc)
            log.warning(
                "charge_autopay: stripe error invoice=%s err=%s",
                invoice_id,
                decline_str,
            )
            return ChargeResult(
                success=False,
                invoice_id=invoice_id,
                status=invoice.status,
                balance_due_cents=invoice.balance_due_cents,
                decline_code=decline_str,
            )

        # 5a. PI declined (gateway returned a decline_code without raising)
        if decline_code is not None:
            log.warning(
                "charge_autopay: PI declined invoice=%s pi=%s code=%s",
                invoice_id,
                pi_id,
                decline_code,
            )
            return ChargeResult(
                success=False,
                invoice_id=invoice_id,
                status=invoice.status,
                balance_due_cents=invoice.balance_due_cents,
                decline_code=decline_code,
            )

        # 5b. PI requires further action (3DS, etc.)
        if pi_status != "succeeded":
            log.info(
                "charge_autopay: PI requires_action invoice=%s pi=%s status=%s",
                invoice_id,
                pi_id,
                pi_status,
            )
            return ChargeResult(
                success=False,
                invoice_id=invoice_id,
                status=invoice.status,
                balance_due_cents=invoice.balance_due_cents,
                requires_action=True,
            )

        # 6. PI succeeded — record LedgerPayment + allocate
        payment_id = f"ledger-pay-autopay:{pi_id}"
        payment = await self._ledger.record_payment(
            LedgerPayment(
                payment_id=payment_id,
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=invoice.balance_due_cents,
                unapplied_amount_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id=pi_id,
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"autopay-pi:{pi_id}",
        )

        allocation_result = await self._ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=invoice.balance_due_cents,
            idempotency_key=f"autopay-alloc:{pi_id}",
        )

        updated_invoice = allocation_result.invoice
        log.info(
            "charge_autopay: succeeded invoice=%s pi=%s new_status=%s balance=%d",
            invoice_id,
            pi_id,
            updated_invoice.status,
            updated_invoice.balance_due_cents,
        )
        return ChargeResult(
            success=True,
            invoice_id=invoice_id,
            status=updated_invoice.status,
            balance_due_cents=updated_invoice.balance_due_cents,
        )
