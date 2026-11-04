"""RecordManualPayment — record a cash/check/manual payment against a LedgerInvoice.

Creates a LedgerPayment (status=paid) and allocates it to the invoice.
The invoice financial status updates from open/partially_paid to paid/partially_paid
based on the allocated amount. Partial payments are allowed. Money beyond the
invoice's balance pays the family's other open invoices oldest-first, and only
what is left after that becomes account credit.

Idempotency: without ``payment_id`` a fresh ULID id is minted per call and the
caller deduplicates (``manual_payment_idempotency``). With a ``payment_id`` derived
from the client's Idempotency-Key the use case is itself idempotent: the ledger
payment and its allocation are keyed on that id, so a retry, or a concurrent
duplicate, converges on the one payment instead of recording another.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.shared.ids import new_ulid

ManualPaymentMethod = Literal["cash", "check", "zelle", "venmo", "bank_transfer", "other"]

_PAYABLE_STATUSES = frozenset({"open", "partially_paid"})


class RecordManualPaymentCommand(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    amount_cents: int = Field(gt=0)
    payment_method: ManualPaymentMethod = "cash"
    reference_number: str | None = None
    notes: str = ""
    #: Deterministic id derived from the client's Idempotency-Key, or None to mint one.
    payment_id: str | None = None


class RecordManualPaymentResult(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int
    overpayment_credit_cents: int = 0
    #: Part of the payment that settled the family's other open invoices.
    previous_balance_applied_cents: int = 0


class RecordManualPayment:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._now = clock

    async def execute(self, cmd: RecordManualPaymentCommand) -> RecordManualPaymentResult:
        if cmd.payment_id is not None:
            # A retry of a submission whose money already moved (the process died
            # before the caller cached the result): resume the spread rather than
            # tripping the "not payable" guard on the invoice it just paid. Every
            # step below is keyed, so finished steps replay and missing ones run.
            if await self._ledger.get_payment_allocation_by_idempotency_key(
                f"alloc-{cmd.payment_id}"
            ):
                invoice = await self._ledger.get_invoice(cmd.invoice_id)
                if invoice is None:
                    raise ValueError(f"invoice {cmd.invoice_id!r} not found")
                return await self._spread(cmd, invoice, cmd.payment_id)
        invoice = await self._ledger.get_invoice(cmd.invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {cmd.invoice_id!r} not found")
        if invoice.status not in _PAYABLE_STATUSES:
            raise ValueError(
                f"invoice {cmd.invoice_id!r} is not payable (status={invoice.status!r})"
            )
        if invoice.balance_due_cents <= 0:
            # The #533 domain change lets async settlement paths (late ACH webhooks)
            # convert money on a zero-balance invoice into an account credit instead
            # of stranding it. A manual payment is a synchronous admin action, so
            # keep the pre-#533 behavior here: reject it up front (before creating a
            # LedgerPayment) rather than silently turning cash into account credit.
            raise ValueError(
                f"invoice {cmd.invoice_id!r} has no balance due; "
                "record an account credit instead of a manual payment"
            )

        now = self._now()
        payment_id = cmd.payment_id or f"manual-{new_ulid()}"
        payment = LedgerPayment(
            payment_id=payment_id,
            academy_id=invoice.academy_id,
            parent_id=invoice.parent_id,
            amount_cents=cmd.amount_cents,
            unapplied_amount_cents=cmd.amount_cents,
            status="succeeded",
            payment_method=cmd.payment_method,
            paid_at=now,
            currency=invoice.currency,
            created_at=now,
            updated_at=now,
        )
        await self._ledger.record_payment(payment, idempotency_key=f"manual-payment-{payment_id}")
        return await self._spread(cmd, invoice, payment_id)

    async def _spread(
        self, cmd: RecordManualPaymentCommand, invoice: LedgerInvoice, payment_id: str
    ) -> RecordManualPaymentResult:
        """Pay the chosen invoice, then the family's other open balances, then credit.

        Owner decision 2026-10-29: money over the chosen invoice's balance settles
        the family's other open invoices oldest-first before any of it becomes
        account credit (a $300 Zelle against one $60 month used to strand $240 as
        credit while four older months stayed unpaid).
        """
        alloc_key = f"alloc-{payment_id}"
        existing = await self._ledger.get_payment_allocation_by_idempotency_key(alloc_key)
        target_cents = (
            existing.amount_cents
            if existing is not None
            else min(cmd.amount_cents, invoice.balance_due_cents)
        )
        target = await self._ledger.allocate_payment(
            payment_id=payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=target_cents,
            idempotency_key=alloc_key,
        )
        remaining = cmd.amount_cents - target_cents
        previous_balance_cents = 0
        if remaining > 0:
            # shortcut: one query capped at 1,000 invoices per family (decades of
            # monthly billing); page through the ledger if a family ever nears it.
            family = await self._ledger.list_invoices_for_parent_aliases(
                [invoice.parent_id], limit=1_000
            )
            others = sorted(
                (other for other in family if other.invoice_id != invoice.invoice_id),
                key=lambda other: (other.due_date, other.invoice_id),
            )
            for other in others:
                key = f"alloc-{payment_id}:{other.invoice_id}"
                # Check the key before the invoice's status: on a resumed retry the
                # invoices this payment already settled read as paid, and their
                # money must still count against what is left to spread.
                done = await self._ledger.get_payment_allocation_by_idempotency_key(key)
                if done is not None:
                    amount = done.amount_cents
                elif remaining > 0 and other.status in _PAYABLE_STATUSES:
                    amount = min(remaining, other.balance_due_cents)
                    if amount <= 0:
                        continue
                    await self._ledger.allocate_payment(
                        payment_id=payment_id,
                        invoice_id=other.invoice_id,
                        amount_cents=amount,
                        idempotency_key=key,
                    )
                else:
                    continue
                remaining -= amount
                previous_balance_cents += amount
        credit_cents = 0
        if remaining > 0:
            # The chosen invoice is now paid, so the domain caps this allocation at
            # zero and mints the remainder as an APPROVED account credit.
            overflow = await self._ledger.allocate_payment(
                payment_id=payment_id,
                invoice_id=invoice.invoice_id,
                amount_cents=remaining,
                idempotency_key=f"alloc-{payment_id}:overpayment",
            )
            if overflow.overpayment_credit is not None:
                credit_cents = overflow.overpayment_credit.amount_cents
        return RecordManualPaymentResult(
            invoice_id=invoice.invoice_id,
            payment_id=payment_id,
            invoice_status=target.invoice.status,
            balance_due_cents=target.invoice.balance_due_cents,
            overpayment_credit_cents=credit_cents,
            previous_balance_applied_cents=previous_balance_cents,
        )
