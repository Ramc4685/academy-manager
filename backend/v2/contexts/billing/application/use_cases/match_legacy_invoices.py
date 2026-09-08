"""Link a legacy Stripe charge to an invoice by hand (issue #242 WI-3).

Migrated/legacy invoices are ``open``/``partially_paid`` and their historical
Stripe payments carry no app metadata, so the reconciler can never auto-match
them (``scanned=0``). Blind auto-matching on amount alone would mis-apply money,
so an admin names both ids explicitly. Confirmation records a back-dated
``LedgerPayment`` + ``PaymentAllocation``, idempotent by
``legacy-match:{charge_id}:{invoice_id}``.

The list half of this (``ListLegacyMatchQueue``) was deleted by the Billing
Health trim (spec 2026-09-07 §2): it recomputed "every open invoice with no
allocation" on each load and fanned out one Stripe ``list_charges`` call per
row, so in production it presented ordinary unpaid invoices as migrated ones.
Nothing here ever auto-confirms; the admin picks the charge.

**The charge is verified against Stripe here, not trusted from the caller.**
The deleted list was doing that verification — it only ever offered charges that
were succeeded, unrefunded, currency-matched, amount-matched and absent from the
ledger, and it passed the charge's real ``payment_intent`` through. Removing it
left the confirm route accepting three owner-typed strings, which is how a typo
became a fabricated payment and how a charge already recorded under its real
payment-intent id could be recorded a second time under its charge id. So the
guarantees moved here, where the one remaining path can enforce them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    LedgerRepository,
    ParentStripeCustomerRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.ledger import LedgerPayment

_PAYABLE_STATUSES = frozenset({"open", "partially_paid"})


class ConfirmLegacyMatchCommand(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    stripe_charge_id: str
    amount_cents: int = Field(gt=0)
    paid_at: datetime | None = None
    recorded_by: str | None = None


class ConfirmLegacyMatchResult(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int


class ConfirmLegacyMatch:
    """Record a back-dated ledger payment for an admin-confirmed legacy charge."""

    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        stripe: StripeGateway,
        parent_customers: ParentStripeCustomerRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._stripe = stripe
        self._parent_customers = parent_customers
        self._now = clock

    async def _verified_charge(
        self, invoice: Any, cmd: ConfirmLegacyMatchCommand
    ) -> dict[str, Any]:
        """Fetch the named charge from Stripe and refuse anything unsafe.

        Listing by the invoice's parent is also the parent binding: a charge id
        belonging to some other family is simply not in this customer's list, so
        it can never be attached here.
        """
        customer_id = await self._parent_customers.get_stripe_customer_id(
            parent_id=invoice.parent_id
        )
        if not customer_id:
            raise ValueError(
                "this parent has no Stripe customer on file, so a charge cannot be verified"
            )

        charges = await self._stripe.list_charges_for_customer(stripe_customer_id=customer_id)
        charge = next(
            (c for c in charges if str(c.get("id") or "") == cmd.stripe_charge_id),
            None,
        )
        if charge is None:
            raise ValueError(
                f"charge {cmd.stripe_charge_id!r} was not found on this parent's Stripe customer"
            )

        if str(charge.get("status") or "").lower() != "succeeded":
            raise ValueError(f"charge {cmd.stripe_charge_id!r} did not succeed")
        if not charge.get("paid", True) or charge.get("refunded"):
            raise ValueError(f"charge {cmd.stripe_charge_id!r} was refunded or never paid")

        amount = int(charge.get("amount") or 0)
        if amount <= 0:
            raise ValueError(f"charge {cmd.stripe_charge_id!r} has no amount")
        if amount != cmd.amount_cents:
            # The typed amount is a cross-check, not the source of truth. Without
            # this, typing the invoice balance instead of the charge amount books
            # money nobody paid and stops the parent being dunned for it.
            raise ValueError(
                f"amount_cents {cmd.amount_cents} does not match the Stripe charge amount {amount}"
            )

        invoice_currency = str(invoice.currency or "usd").lower()
        if str(charge.get("currency") or invoice_currency).lower() != invoice_currency:
            raise ValueError(
                f"charge {cmd.stripe_charge_id!r} is not in {invoice_currency.upper()}"
            )

        return charge

    async def execute(self, cmd: ConfirmLegacyMatchCommand) -> ConfirmLegacyMatchResult:
        allocation_key = f"legacy-match:{cmd.stripe_charge_id}:{cmd.invoice_id}"
        # Idempotent rerun: if this exact match was already confirmed the invoice
        # may now be ``paid`` (and thus fail the payability guard below), so
        # short-circuit on the allocation key and report the current state.
        existing = await self._ledger.get_payment_allocation_by_idempotency_key(allocation_key)
        if existing is not None:
            invoice = await self._ledger.get_invoice(cmd.invoice_id)
            return ConfirmLegacyMatchResult(
                invoice_id=cmd.invoice_id,
                payment_id=existing.payment_id,
                invoice_status=invoice.status if invoice else "paid",
                balance_due_cents=invoice.balance_due_cents if invoice else 0,
            )

        invoice = await self._ledger.get_invoice(cmd.invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {cmd.invoice_id!r} not found")
        if invoice.status not in _PAYABLE_STATUSES:
            raise ValueError(
                f"invoice {cmd.invoice_id!r} is not payable (status={invoice.status!r})"
            )
        if cmd.amount_cents > invoice.balance_due_cents:
            raise ValueError(
                f"amount_cents {cmd.amount_cents} exceeds "
                f"balance_due_cents {invoice.balance_due_cents}"
            )

        charge = await self._verified_charge(invoice, cmd)

        # Stripe's own payment_intent, never a caller-supplied one. The webhook
        # and reconciler both dedupe on this id; recording the charge id here
        # instead let the same money be booked twice — once by hand and once by
        # a later replay — with the duplicate landing as parent credit.
        pi = charge.get("payment_intent")
        pi_id = str(pi) if pi else None
        ledger_key = pi_id or cmd.stripe_charge_id
        already = await self._ledger.get_payment_by_stripe_payment_intent_id(ledger_key)
        if already is not None:
            raise ValueError(
                f"charge {cmd.stripe_charge_id!r} is already recorded as payment "
                f"{already.payment_id!r}"
            )

        now = self._now()
        paid_at = cmd.paid_at or now
        # Deterministic payment id keyed on the charge → idempotent confirm/reruns.
        payment_id = f"legacy-match-{cmd.stripe_charge_id}"
        payment = await self._ledger.record_payment(
            LedgerPayment(
                payment_id=payment_id,
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=cmd.amount_cents,
                unapplied_amount_cents=cmd.amount_cents,
                currency=invoice.currency,
                status="succeeded",
                payment_method="stripe_legacy",
                stripe_payment_intent_id=ledger_key,
                paid_at=paid_at,
                recorded_by=cmd.recorded_by or "admin_legacy_match",
                notes=f"legacy match: Stripe charge {cmd.stripe_charge_id}",
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"legacy-match-pay:{cmd.stripe_charge_id}",
        )
        result = await self._ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=cmd.invoice_id,
            amount_cents=cmd.amount_cents,
            idempotency_key=allocation_key,
        )
        return ConfirmLegacyMatchResult(
            invoice_id=cmd.invoice_id,
            payment_id=payment.payment_id,
            invoice_status=result.invoice.status,
            balance_due_cents=result.invoice.balance_due_cents,
        )
