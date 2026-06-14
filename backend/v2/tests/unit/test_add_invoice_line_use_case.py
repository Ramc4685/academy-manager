"""Unit tests for AddInvoiceLine use case (in-memory fake, no Mongo)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

# ---------------------------------------------------------------------------
# In-memory fake repository
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
DUE = date(2026, 6, 30)


def _open_invoice(
    invoice_id: str = "inv-1",
    student_id: str = "s1",
    period: str = "2026-06",
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        student_id=student_id,
        period=period,
        status="open",
        subtotal_cents=0,
        discount_cents=0,
        total_cents=0,
        balance_due_cents=0,
        currency="usd",
        due_date=DUE,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeLedgerRepository:
    """Minimal in-memory implementation of LedgerRepository for use-case tests."""

    def __init__(self, invoices: list[LedgerInvoice] | None = None) -> None:
        self._invoices: dict[str, LedgerInvoice] = (
            {inv.invoice_id: inv for inv in invoices} if invoices else {}
        )
        self._lines: dict[str, InvoiceLine] = {}

    # --- LedgerRepository protocol methods ---

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        for inv in self._invoices.values():
            if (
                inv.student_id == student_id
                and inv.period == period
                and inv.status in ("open", "draft", "partially_paid")
            ):
                return inv
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [ln for ln in self._lines.values() if ln.invoice_id == invoice_id]

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        return invoice

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        self._lines[line.line_id] = line
        return line

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        for ln in lines:
            self._lines[ln.line_id] = ln
        return invoice


# ---------------------------------------------------------------------------
# Helper: build and execute use case
# ---------------------------------------------------------------------------


def _use_case(repo: FakeLedgerRepository) -> AddInvoiceLine:
    return AddInvoiceLine(ledger=repo, clock=lambda: NOW)


def _line_cmd(**overrides) -> dict:
    base = {
        "description": "June tuition",
        "line_type": "tuition",
        "quantity": 1,
        "unit_amount_cents": 5_000,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Mode A — explicit invoice_id
# ---------------------------------------------------------------------------


async def test_mode_a_adds_line_to_existing_invoice() -> None:
    repo = FakeLedgerRepository(invoices=[_open_invoice()])
    uc = _use_case(repo)

    result = await uc.execute(AddInvoiceLineCommand(invoice_id="inv-1", **_line_cmd()))

    assert result.invoice.invoice_id == "inv-1"
    assert result.invoice.subtotal_cents == 5_000
    assert result.line.amount_cents == 5_000
    # Line persisted
    lines = await repo.get_lines_for_invoice("inv-1")
    assert len(lines) == 1


async def test_mode_a_raises_when_invoice_not_found() -> None:
    repo = FakeLedgerRepository()  # empty
    uc = _use_case(repo)

    with pytest.raises(ValueError, match="inv-missing not found"):
        await uc.execute(AddInvoiceLineCommand(invoice_id="inv-missing", **_line_cmd()))


# ---------------------------------------------------------------------------
# Mode B — on-the-fly invoice creation
# ---------------------------------------------------------------------------


async def test_mode_b_creates_invoice_when_none_exists() -> None:
    """Gap 1: AddInvoiceLine creates an open invoice on the fly if none exists."""
    repo = FakeLedgerRepository()  # no invoices
    uc = _use_case(repo)

    result = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s1",
            period="2026-06",
            academy_id="acad-1",
            parent_id="parent-1",
            **_line_cmd(),
        )
    )

    # Deterministic invoice_id
    assert result.invoice.invoice_id == "inv-s1-2026-06"
    assert result.invoice.status == "open"
    assert result.invoice.student_id == "s1"
    assert result.invoice.period == "2026-06"
    assert result.invoice.subtotal_cents == 5_000
    assert result.line.invoice_id == "inv-s1-2026-06"

    # Invoice was persisted
    stored = await repo.get_invoice("inv-s1-2026-06")
    assert stored is not None


async def test_mode_b_reuses_existing_open_invoice() -> None:
    """Mode B reuses the student's existing open invoice instead of creating a duplicate."""
    existing = _open_invoice(invoice_id="inv-existing", student_id="s1", period="2026-06")
    repo = FakeLedgerRepository(invoices=[existing])
    uc = _use_case(repo)

    result = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s1",
            period="2026-06",
            **_line_cmd(),
        )
    )

    # Used the existing invoice, not a new one
    assert result.invoice.invoice_id == "inv-existing"
    # No spurious second invoice created
    assert len(repo._invoices) == 1


async def test_mode_b_due_date_is_last_day_of_period() -> None:
    """On-the-fly invoice due_date is the last day of the given month."""
    repo = FakeLedgerRepository()
    uc = _use_case(repo)

    result = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s2",
            period="2026-02",
            **_line_cmd(),
        )
    )

    assert result.invoice.due_date == date(2026, 2, 28)


async def test_mode_b_december_due_date() -> None:
    """December period wraps year correctly."""
    repo = FakeLedgerRepository()
    uc = _use_case(repo)

    result = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s3",
            period="2026-12",
            **_line_cmd(),
        )
    )

    assert result.invoice.due_date == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# Idempotency: save_line is an upsert, so re-saving same line_id is safe
# ---------------------------------------------------------------------------


async def test_save_line_upsert_does_not_duplicate() -> None:
    """Gap 2: save_line with the same line_id is an upsert — calling it twice
    leaves exactly one line stored (idempotent)."""
    repo = FakeLedgerRepository(invoices=[_open_invoice()])

    line = InvoiceLine(
        line_id="line-fixed",
        academy_id="acad-1",
        invoice_id="inv-1",
        line_type="tuition",
        description="June tuition",
        quantity=1,
        unit_amount_cents=5_000,
        amount_cents=5_000,
        created_at=NOW,
    )

    # Save the same line twice (simulates a retry or double-call)
    await repo.save_line(line)
    await repo.save_line(line)

    lines = await repo.get_lines_for_invoice("inv-1")
    assert len(lines) == 1, "save_line must be idempotent — no duplicate lines"


# ---------------------------------------------------------------------------
# Command validation
# ---------------------------------------------------------------------------


def test_command_raises_when_neither_mode_provided() -> None:
    """Command validator rejects commands that specify neither invoice_id nor student+period."""
    with pytest.raises(ValueError, match="invoice_id"):
        AddInvoiceLineCommand(**_line_cmd())
