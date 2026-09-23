"""RecordManualPayment — record a cash/check/manual payment against a LedgerInvoice.

Creates a LedgerPayment (status=paid) and allocates it to the invoice.
The invoice financial status updates from open/partially_paid to paid/partially_paid
based on the allocated amount. Partial payments are allowed.

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
from backend.v2.contexts.billing.domain.ledger import LedgerAllocationResult, LedgerPayment
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
            # before the caller cached the result): replay the allocation rather
            # than tripping the "not payable" guard on the invoice it just paid.
            alloc_key = f"alloc-{cmd.payment_id}"
            if await self._ledger.get_payment_allocation_by_idempotency_key(alloc_key):
                replayed = await self._ledger.allocate_payment(
                    payment_id=cmd.payment_id,
                    invoice_id=cmd.invoice_id,
                    amount_cents=cmd.amount_cents,
                    idempotency_key=alloc_key,
                )
                return _result(cmd.invoice_id, cmd.payment_id, replayed)
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
        # Partial overpayment is allowed: the allocation caps to the invoice balance
        # and the remainder becomes an APPROVED account credit (same as the Stripe
        # path), so the manual and automated payment paths behave identically.

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
        payment = await self._ledger.record_payment(
            payment, idempotency_key=f"manual-payment-{payment_id}"
        )
        result = await self._ledger.allocate_payment(
            payment_id=payment_id,
            invoice_id=cmd.invoice_id,
            amount_cents=cmd.amount_cents,
            idempotency_key=f"alloc-{payment_id}",
        )
        return _result(cmd.invoice_id, payment_id, result)


def _result(
    invoice_id: str, payment_id: str, result: LedgerAllocationResult
) -> RecordManualPaymentResult:
    return RecordManualPaymentResult(
        invoice_id=invoice_id,
        payment_id=payment_id,
        invoice_status=result.invoice.status,
        balance_due_cents=result.invoice.balance_due_cents,
        overpayment_credit_cents=(
            result.overpayment_credit.amount_cents if result.overpayment_credit else 0
        ),
    )
