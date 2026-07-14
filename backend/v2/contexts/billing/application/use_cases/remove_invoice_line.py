"""RemoveInvoiceLine use case — delete draft invoice lines and recompute totals."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, recompute_totals


class RemoveInvoiceLineCommand(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str = Field(min_length=1)
    line_id: str = Field(min_length=1)


class RemoveInvoiceLineResult(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice


class RemoveInvoiceLine:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._clock = clock

    async def execute(self, cmd: RemoveInvoiceLineCommand) -> RemoveInvoiceLineResult:
        invoice = await self._ledger.get_invoice(cmd.invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {cmd.invoice_id} not found")
        if invoice.status != "draft":
            raise ValueError(f"can only remove lines from a draft invoice, got {invoice.status}")

        deleted = await self._ledger.delete_invoice_line(
            invoice_id=cmd.invoice_id,
            line_id=cmd.line_id,
        )
        if not deleted:
            raise LookupError(f"line {cmd.line_id} not found")

        remaining_lines = await self._ledger.get_lines_for_invoice(cmd.invoice_id)
        allocated_cents = await self._ledger.sum_allocations_for_invoice(cmd.invoice_id)
        updated_invoice = recompute_totals(
            invoice.model_copy(update={"updated_at": self._clock()}),
            remaining_lines,
            allocated_cents=allocated_cents,
        )
        saved_invoice = await self._ledger.save_invoice(updated_invoice)
        return RemoveInvoiceLineResult(invoice=saved_invoice)
