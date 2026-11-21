"""Zero-balance waiver and discount wording in the parent invoice email (#1035)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.email_adapters import InvoiceAdjustment, InvoiceNaming
from backend.v2.composition.invoice_naming import build_invoice_naming_resolver
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.unit.test_invoice_email_naming import _adapter, _FakeSender

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 1, tzinfo=UTC)


async def _send(naming: InvoiceNaming, *, total: int, balance: int) -> str:
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=naming).send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            total_cents=total,
            balance_due_cents=balance,
            currency="usd",
            checkout_url=None,
        )
    return sender.calls[0]["body"]


async def test_full_coach_waiver_says_covered_by_the_academy_and_no_payment() -> None:
    naming = InvoiceNaming(
        adjustments=(
            InvoiceAdjustment(
                description="Coach child discount", amount_cents=-10_000, category="coach_child"
            ),
        )
    )

    body = await _send(naming, total=0, balance=0)

    # The academy's own name, never a hard-coded one.
    assert "Coach benefit: fees covered by Test Academy" in body
    assert "No payment required" in body
    assert "arrange payment" not in body
    assert "Pay invoice" not in body
    assert "BLNO" not in body


async def test_partial_discount_is_named_with_its_amount() -> None:
    naming = InvoiceNaming(
        adjustments=(
            InvoiceAdjustment(
                description="Sibling discount", amount_cents=-1_000, category="sibling"
            ),
        )
    )

    body = await _send(naming, total=9_000, balance=9_000)

    assert "Sibling discount" in body
    assert "-$10.00" in body
    assert "No payment required" not in body


async def test_partial_coach_discount_keeps_its_own_description() -> None:
    naming = InvoiceNaming(
        adjustments=(
            InvoiceAdjustment(
                description="Coach child discount", amount_cents=-5_000, category="coach_child"
            ),
        )
    )

    body = await _send(naming, total=5_000, balance=5_000)

    assert "Coach child discount" in body
    assert "fees covered by" not in body


async def test_autopay_notice_names_the_discount() -> None:
    naming = InvoiceNaming(
        adjustments=(
            InvoiceAdjustment(
                description="Sibling discount", amount_cents=-1_000, category="sibling"
            ),
        )
    )
    sender = _FakeSender()
    with tenant_scope("acad"):
        await _adapter(sender, naming=naming).send_autopay_notice(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-09",
            amount_cents=9_000,
            currency="usd",
            charge_on=date(2026, 9, 10),
            portal_url=None,
        )

    body = sender.calls[0]["body"]
    assert "Sibling discount" in body
    assert "-$10.00" in body


async def test_adjustment_description_is_escaped() -> None:
    naming = InvoiceNaming(
        adjustments=(InvoiceAdjustment(description="<b>x</b>", amount_cents=-100),)
    )

    body = await _send(naming, total=0, balance=0)

    assert "<b>x</b>" not in body
    assert "&lt;b&gt;x&lt;/b&gt;" in body


class _Ledger:
    def __init__(self, invoice: LedgerInvoice, lines: list[InvoiceLine]) -> None:
        self._invoice, self._lines = invoice, lines

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoice if invoice_id == self._invoice.invoice_id else None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [line for line in self._lines if line.invoice_id == invoice_id]


def _line(line_type: str, amount: int, description: str, **extra: object) -> InvoiceLine:
    return InvoiceLine(
        line_id=f"line-{line_type}-{amount}",
        academy_id="acad",
        invoice_id="inv-1",
        line_type=line_type,
        description=description,
        quantity=1,
        unit_amount_cents=amount,
        amount_cents=amount,
        created_at=NOW,
        **extra,
    )


async def test_resolver_carries_discount_and_credit_lines_but_not_charges() -> None:
    invoice = LedgerInvoice(
        invoice_id="inv-1",
        academy_id="acad",
        parent_id="parent-1",
        period="2026-09",
        invoice_number="TA-2026-09-0001",
        subtotal_cents=10_000,
        discount_cents=10_000,
        total_cents=0,
        balance_due_cents=0,
        due_date=date(2026, 9, 10),
        created_at=NOW,
        updated_at=NOW,
    )
    ledger = _Ledger(
        invoice,
        [
            _line("tuition", 10_000, "Monthly tuition"),
            _line("discount", -10_000, "Coach child discount", category="coach_child"),
            _line("adjustment", -500, "Goodwill credit"),
        ],
    )
    resolve = build_invoice_naming_resolver(
        ledger=ledger,
        db=AsyncMongoMockClient()["t"],
        billing_counters=None,
        billing_settings=None,
        now=lambda: NOW,
    )

    with tenant_scope("acad"):
        naming = await resolve("inv-1")

    assert naming.adjustments == (
        InvoiceAdjustment(
            description="Coach child discount", amount_cents=-10_000, category="coach_child"
        ),
        InvoiceAdjustment(description="Goodwill credit", amount_cents=-500),
    )
