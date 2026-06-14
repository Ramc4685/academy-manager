"""AddInvoiceLine use case — append a charge line to an open/draft invoice."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    InvoiceLineAdded,
    LedgerInvoice,
    add_line,
)
from backend.v2.shared.ids import new_ulid

logger = logging.getLogger(__name__)


class AddInvoiceLineCommand(BaseModel):
    model_config = {"frozen": True}

    invoice_id: str
    description: str = Field(min_length=1)
    line_type: str = Field(min_length=1)
    quantity: int = Field(ge=1, default=1)
    unit_amount_cents: int
    source_type: str | None = None
    source_id: str | None = None
    product_id: str | None = None  # informational only — prefills description/type at call site


class AddInvoiceLineResult(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice
    line: InvoiceLine


class AddInvoiceLine:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._clock = clock

    async def execute(self, cmd: AddInvoiceLineCommand) -> AddInvoiceLineResult:
        now = self._clock()

        invoice = await self._ledger.get_invoice(cmd.invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {cmd.invoice_id} not found")

        existing_lines = await self._ledger.get_lines_for_invoice(cmd.invoice_id)

        amount_cents = cmd.quantity * cmd.unit_amount_cents
        new_line = InvoiceLine(
            line_id=f"line-{new_ulid()}",
            academy_id=invoice.academy_id,
            invoice_id=invoice.invoice_id,
            line_type=cmd.line_type,
            description=cmd.description,
            quantity=cmd.quantity,
            unit_amount_cents=cmd.unit_amount_cents,
            amount_cents=amount_cents,
            source_type=cmd.source_type,
            source_id=cmd.source_id,
            created_at=now,
        )

        updated_invoice, _ = add_line(invoice, existing_lines, new_line, now=now)

        saved_invoice = await self._ledger.save_invoice(updated_invoice)
        await self._ledger.save_line(new_line)

        event = InvoiceLineAdded(
            invoice_id=saved_invoice.invoice_id,
            line_id=new_line.line_id,
            academy_id=saved_invoice.academy_id,
        )
        logger.info("InvoiceLineAdded: %s", event)

        return AddInvoiceLineResult(invoice=saved_invoice, line=new_line)
