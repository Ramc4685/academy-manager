"""Human-reviewed match queue for legacy invoices ↔ Stripe charges (issue #242 WI-3).

Migrated/legacy invoices are ``open``/``partially_paid`` and their historical
Stripe payments carry no app metadata, so the reconciler can never auto-match
them (``scanned=0``). Blind auto-matching on amount alone would mis-apply money.

This module surfaces, per unmatched invoice, the *candidate* Stripe charges for
the parent's customer (amount + date window) with a confidence label, and lets an
admin confirm one explicitly. Confirmation records a back-dated ``LedgerPayment``
+ ``PaymentAllocation``, idempotent by ``legacy-match:{charge_id}:{invoice_id}``.

Nothing here ever auto-confirms; the admin must pick a match.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    LedgerRepository,
    ParentStripeCustomerRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.ledger import LedgerPayment

_PAYABLE_STATUSES = frozenset({"open", "partially_paid"})
# Charges this far from an invoice's due date are still candidates but rank lower.
_CONFIDENT_WINDOW = timedelta(days=31)

Confidence = str  # "high" | "medium"


class MatchQueueLedger(Protocol):
    """Ledger reads needed to build the queue (superset of LedgerRepository)."""

    async def list_unmatched_invoices(self) -> list[dict[str, Any]]: ...
    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None: ...


class CandidateCharge(BaseModel):
    model_config = {"frozen": True}

    stripe_charge_id: str
    stripe_payment_intent_id: str | None = None
    amount_cents: int
    currency: str
    created_at: datetime | None = None
    description: str | None = None
    confidence: Confidence


class MatchQueueRow(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    parent_id: str
    parent_name: str | None = None
    period: str
    status: str
    total_cents: int
    balance_due_cents: int
    currency: str
    due_date: date | None = None
    created_at: datetime | None = None
    stripe_invoice_id: str | None = None
    stripe_customer_id: str | None = None
    candidates: list[CandidateCharge] = Field(default_factory=list)


class ListLegacyMatchQueue:
    """Build the review queue: unmatched invoices + candidate Stripe charges."""

    def __init__(
        self,
        *,
        ledger: MatchQueueLedger,
        stripe: StripeGateway,
        parent_customers: ParentStripeCustomerRepository,
    ) -> None:
        self._ledger = ledger
        self._stripe = stripe
        self._parent_customers = parent_customers

    async def execute(self) -> list[MatchQueueRow]:
        invoices = await self._ledger.list_unmatched_invoices()
        # Cache charges per customer so several invoices for one parent share a fetch.
        charges_cache: dict[str, list[dict[str, Any]]] = {}
        rows: list[MatchQueueRow] = []
        for inv in invoices:
            parent_id = str(inv.get("parent_id") or "")
            customer_id = await self._parent_customers.get_stripe_customer_id(parent_id=parent_id)
            candidates: list[CandidateCharge] = []
            if customer_id:
                if customer_id not in charges_cache:
                    charges_cache[customer_id] = await self._stripe.list_charges_for_customer(
                        stripe_customer_id=customer_id
                    )
                candidates = await self._candidates_for_invoice(inv, charges_cache[customer_id])
            rows.append(
                MatchQueueRow(
                    invoice_id=str(inv.get("invoice_id") or ""),
                    parent_id=parent_id,
                    period=str(inv.get("period") or ""),
                    status=str(inv.get("status") or "open"),
                    total_cents=int(inv.get("total_cents") or 0),
                    balance_due_cents=int(inv.get("balance_due_cents") or 0),
                    currency=str(inv.get("currency") or "usd"),
                    due_date=inv.get("due_date"),
                    created_at=inv.get("created_at"),
                    stripe_invoice_id=inv.get("stripe_invoice_id"),
                    stripe_customer_id=customer_id,
                    candidates=candidates,
                )
            )
        return rows

    async def _candidates_for_invoice(
        self, inv: dict[str, Any], charges: list[dict[str, Any]]
    ) -> list[CandidateCharge]:
        balance_due = int(inv.get("balance_due_cents") or 0)
        total = int(inv.get("total_cents") or 0)
        currency = str(inv.get("currency") or "usd").lower()
        due_date = inv.get("due_date")
        candidates: list[CandidateCharge] = []
        for charge in charges:
            if str(charge.get("status") or "").lower() != "succeeded":
                continue
            if not charge.get("paid", True) or charge.get("refunded"):
                continue
            amount = int(charge.get("amount") or 0)
            if amount <= 0:
                continue
            if str(charge.get("currency") or currency).lower() != currency:
                continue
            if amount != balance_due and amount != total:
                continue
            charge_id = str(charge.get("id") or "")
            if not charge_id:
                continue
            pi = charge.get("payment_intent")
            pi_id = str(pi) if pi else None
            # Skip charges whose payment already exists in the ledger — they were
            # matched (here or by the reconciler) against some invoice already.
            ledger_key = pi_id or charge_id
            if await self._ledger.get_payment_by_stripe_payment_intent_id(ledger_key) is not None:
                continue
            created_at = _epoch_to_datetime(charge.get("created"))
            confidence = _confidence(
                amount=amount,
                balance_due=balance_due,
                created_at=created_at,
                due_date=due_date,
            )
            candidates.append(
                CandidateCharge(
                    stripe_charge_id=charge_id,
                    stripe_payment_intent_id=pi_id,
                    amount_cents=amount,
                    currency=str(charge.get("currency") or currency).lower(),
                    created_at=created_at,
                    description=charge.get("description"),
                    confidence=confidence,
                )
            )
        # Highest confidence first, then most recent charge.
        candidates.sort(
            key=lambda c: (
                0 if c.confidence == "high" else 1,
                -(c.created_at.timestamp() if c.created_at else 0.0),
            )
        )
        return candidates


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


def _epoch_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _confidence(
    *,
    amount: int,
    balance_due: int,
    created_at: datetime | None,
    due_date: Any,
) -> Confidence:
    """High only when the amount clears the balance exactly and the charge is
    close in time to the due date; everything else is medium for human review."""
    if amount != balance_due:
        return "medium"
    if created_at is None or not isinstance(due_date, date):
        return "medium"
    charge_day = created_at.date()
    if abs((charge_day - due_date).days) <= _CONFIDENT_WINDOW.days:
        return "high"
    return "medium"
