"""RecordManualPayment — record a cash/check/manual payment against a LedgerInvoice.

Creates a LedgerPayment (status=paid) and allocates it to the invoice.
The invoice financial status updates from open/partially_paid to paid/partially_paid
based on the allocated amount. Partial payments are allowed.

Idempotency: the payment_id is ULID-generated per call; the caller deduplicates at the
HTTP layer by inspecting the response (or by keying on an external reference_number).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerPayment
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


class RecordManualPaymentResult(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int


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
        payment_id = f"manual-{new_ulid()}"
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
        return RecordManualPaymentResult(
            invoice_id=cmd.invoice_id,
            payment_id=payment_id,
            invoice_status=result.invoice.status,
            balance_due_cents=result.invoice.balance_due_cents,
        )
