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
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerPayment

_PAYABLE_STATUSES = frozenset({"open", "partially_paid"})


class ConfirmLegacyMatchCommand(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    stripe_charge_id: str
    amount_cents: int = Field(gt=0)
    stripe_payment_intent_id: str | None = None
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
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._now = clock

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
                stripe_payment_intent_id=cmd.stripe_payment_intent_id or cmd.stripe_charge_id,
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
