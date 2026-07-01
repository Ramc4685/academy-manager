"""AddInvoiceLine use case — append a charge line to an open/draft invoice.

Two calling modes
-----------------
Mode A — ``invoice_id`` provided:
    Looks up the invoice by ID (raises ValueError if not found).

Mode B — ``student_id`` + ``period`` provided, ``invoice_id=None``:
    Looks up the student's open invoice for that period.  If none exists,
    creates a new ``LedgerInvoice(status="open")`` with a deterministic
    ``invoice_id = f"inv-{student_id}-{period}"`` and saves it, then adds
    the line to that invoice. A fresh invoice also mints ``invoice_number``
    (Slice D) via the atomic per-academy/month counter and the academy's
    configured prefix — see ``format_invoice_number``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from backend.v2.contexts.billing.application.ports import (
    BillingCounterRepository,
    BillingSettingsRepository,
    LedgerRepository,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    InvoiceLineAdded,
    LedgerInvoice,
    add_line,
    format_invoice_number,
)
from backend.v2.shared.ids import new_ulid

logger = logging.getLogger(__name__)


class AddInvoiceLineCommand(BaseModel):
    model_config = {"frozen": True}

    # --- Mode A: explicit invoice lookup ---
    invoice_id: str | None = None

    # --- Mode B: student + period → look-up or create-on-the-fly ---
    student_id: str | None = None
    period: str | None = None  # "YYYY-MM"

    # Shared fields for the new line
    description: str = Field(min_length=1)
    line_type: str = Field(min_length=1)
    quantity: int = Field(ge=1, default=1)
    unit_amount_cents: int
    source_type: str | None = None
    source_id: str | None = None
    product_id: str | None = None  # informational only — prefills description/type at call site

    # Required in Mode B so the created invoice has the right parent/academy
    academy_id: str | None = None
    parent_id: str | None = None

    @model_validator(mode="after")
    def _check_mode(self) -> AddInvoiceLineCommand:
        has_invoice = self.invoice_id is not None
        has_student = self.student_id is not None and self.period is not None
        if not has_invoice and not has_student:
            raise ValueError("provide either invoice_id (Mode A) or student_id + period (Mode B)")
        if not has_invoice:
            # Mode B: academy_id and parent_id are required to create an on-the-fly invoice
            if not self.academy_id:
                raise ValueError("academy_id is required in Mode B (invoice_id not provided)")
            if not self.parent_id:
                raise ValueError("parent_id is required in Mode B (invoice_id not provided)")
        return self


class AddInvoiceLineResult(BaseModel):
    model_config = {"frozen": True}

    invoice: LedgerInvoice
    line: InvoiceLine


class AddInvoiceLine:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        counters: BillingCounterRepository | None = None,
        settings: BillingSettingsRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._counters = counters
        self._settings = settings
        self._clock = clock

    async def execute(self, cmd: AddInvoiceLineCommand) -> AddInvoiceLineResult:
        now = self._clock()

        invoice = await self._resolve_invoice(cmd, now)

        existing_lines = await self._ledger.get_lines_for_invoice(invoice.invoice_id)

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_invoice(self, cmd: AddInvoiceLineCommand, now: datetime) -> LedgerInvoice:
        """Return the invoice to add a line to, creating one on-the-fly if needed."""

        # --- Mode A: explicit invoice_id ---
        if cmd.invoice_id is not None:
            invoice = await self._ledger.get_invoice(cmd.invoice_id)
            if invoice is None:
                raise ValueError(f"invoice {cmd.invoice_id} not found")
            return invoice

        # --- Mode B: student + period ---
        assert cmd.student_id is not None and cmd.period is not None  # validated above

        existing = await self._ledger.get_open_invoice_for_student(cmd.student_id, cmd.period)
        if existing is not None:
            return existing

        # Create a new open invoice on the fly with a deterministic ID
        invoice_id = f"inv-{cmd.student_id}-{cmd.period}"
        # Derive a due date: last day of the given month
        year, month = (int(p) for p in cmd.period.split("-"))
        if month == 12:
            due_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            due_date = date(year, month + 1, 1) - timedelta(days=1)

        invoice_number = await self._mint_invoice_number(
            academy_id=cmd.academy_id, period=cmd.period
        )

        new_invoice = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=cmd.academy_id,
            parent_id=cmd.parent_id,
            student_id=cmd.student_id,
            period=cmd.period,
            status="open",
            subtotal_cents=0,
            discount_cents=0,
            total_cents=0,
            balance_due_cents=0,
            currency="usd",
            due_date=due_date,
            invoice_number=invoice_number,
            created_at=now,
            updated_at=now,
        )
        saved = await self._ledger.save_invoice(new_invoice)
        logger.info(
            "Created on-the-fly invoice %s for student %s period %s",
            invoice_id,
            cmd.student_id,
            cmd.period,
        )
        return saved

    async def _mint_invoice_number(self, *, academy_id: str, period: str) -> str | None:
        """Mint a human-facing invoice number for a brand-new invoice.

        Returns ``None`` (rather than raising) when ``counters``/``settings`` were not
        wired into this use case — callers that predate Slice D keep working unchanged,
        just without an invoice_number. Once wired, minting is atomic and race-safe
        (MongoBillingCounterRepository.next_value uses find_one_and_update + $inc), so
        concurrent invoice creation for the same academy+month never collides.
        """
        if self._counters is None or self._settings is None:
            return None
        yyyymm = period.replace("-", "")
        settings = await self._settings.get()
        seq = await self._counters.next_value(scope=f"invoice:{academy_id}:{yyyymm}")
        return format_invoice_number(prefix=settings.invoice_number_prefix, yyyymm=yyyymm, seq=seq)
