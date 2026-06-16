"""Unit tests for SendInvoice use case (in-memory fake, no Mongo, no Stripe, no email).

Key invariant: financial status is NEVER changed by SendInvoice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC)
DUE = date(2026, 6, 30)
FIRST_SEND = datetime(2026, 6, 13, 9, 0, 0, tzinfo=UTC)  # earlier than NOW


def _invoice(
    invoice_id: str = "inv-1",
    status: str = "open",
    balance_due_cents: int = 10_000,
    delivery_status: str = "not_sent",
    sent_at: datetime | None = None,
    last_sent_at: datetime | None = None,
) -> LedgerInvoice:
    total = 10_000
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="s-1",
        period="2026-06",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=total,
        discount_cents=0,
        total_cents=total,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=DUE,
        delivery_status=delivery_status,  # type: ignore[arg-type]
        sent_at=sent_at,
        last_sent_at=last_sent_at,
        created_at=FIRST_SEND,
        updated_at=FIRST_SEND,
    )


# ---------------------------------------------------------------------------
# Fake ledger repo
# ---------------------------------------------------------------------------


class FakeLedgerRepository:
    def __init__(self, invoices: list[LedgerInvoice] | None = None) -> None:
        self._invoices: dict[str, LedgerInvoice] = (
            {inv.invoice_id: inv for inv in invoices} if invoices else {}
        )
        self._lines: dict[str, InvoiceLine] = {}
        self.save_calls: list[LedgerInvoice] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [ln for ln in self._lines.values() if ln.invoice_id == invoice_id]

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        self.save_calls.append(invoice)
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
        return invoice


# ---------------------------------------------------------------------------
# Use-case factory
# ---------------------------------------------------------------------------


def _uc(repo: FakeLedgerRepository) -> SendInvoice:
    """Build SendInvoice with no Stripe/email — just the ledger."""
    return SendInvoice(ledger=repo, stripe=None, email=None, clock=lambda: NOW)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_send_draft_invoice_finalizes_then_records_delivery() -> None:
    """Draft invoice: finalized first (status→open), then delivery recorded."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="draft")])
    result = await _uc(repo).execute("inv-1")

    assert result.invoice.status == "open", "financial status must be 'open' after finalize+send"
    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == NOW
    assert result.invoice.last_sent_at == NOW


async def test_send_open_invoice_records_delivery_without_changing_status() -> None:
    """Open invoice: delivery recorded, financial status remains 'open'."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open")])
    result = await _uc(repo).execute("inv-1")

    assert result.invoice.status == "open"
    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == NOW
    assert result.invoice.last_sent_at == NOW


async def test_send_partially_paid_invoice_keeps_status() -> None:
    """Partially paid invoice: delivery recorded, financial status stays 'partially_paid'."""
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="partially_paid", balance_due_cents=3_000)]
    )
    result = await _uc(repo).execute("inv-1")

    assert result.invoice.status == "partially_paid"
    assert result.invoice.delivery_status == "sent"


async def test_resend_updates_last_sent_at_but_preserves_sent_at() -> None:
    """Re-send: last_sent_at moves to NOW, sent_at stays as first-send timestamp."""
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(
                delivery_status="sent",
                sent_at=FIRST_SEND,
                last_sent_at=FIRST_SEND,
            )
        ]
    )
    result = await _uc(repo).execute("inv-1")

    # sent_at must not be overwritten (first-send preserved)
    assert result.invoice.sent_at == FIRST_SEND, "sent_at must be the first-send timestamp"
    # last_sent_at reflects this re-send
    assert result.invoice.last_sent_at == NOW
    assert result.invoice.delivery_status == "sent"


async def test_financial_status_unchanged_by_send_key_invariant() -> None:
    """Core invariant: no matter what status the invoice is in, SendInvoice
    never changes the financial status (except draft→open via finalize)."""
    for initial_status, expected_status in [
        ("open", "open"),
        ("partially_paid", "partially_paid"),
        ("paid", "paid"),
    ]:
        balance = 0 if initial_status == "paid" else 5_000
        repo = FakeLedgerRepository(
            invoices=[_invoice(status=initial_status, balance_due_cents=balance)]
        )
        result = await _uc(repo).execute("inv-1")
        assert (
            result.invoice.status == expected_status
        ), f"financial status changed from {initial_status!r} to {result.invoice.status!r}"


async def test_raises_when_invoice_not_found() -> None:
    """Missing invoice_id raises ValueError."""
    repo = FakeLedgerRepository()
    with pytest.raises(ValueError, match="inv-missing"):
        await _uc(repo).execute("inv-missing")


async def test_checkout_url_is_none_when_no_stripe_configured() -> None:
    """When no Stripe gateway is injected, checkout_url is None."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=5_000)])
    result = await _uc(repo).execute("inv-1")
    assert result.checkout_url is None


async def test_no_checkout_session_when_balance_is_zero() -> None:
    """Already paid invoice (balance==0): no Stripe call even if gateway present."""

    class _FakeStripe:
        called = False

        async def create_invoice_checkout_session(self, **kwargs) -> tuple[str, str]:  # type: ignore[override]
            self.called = True
            return ("cs_fake", "https://checkout.stripe.com/fake")

    stripe = _FakeStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="paid", balance_due_cents=0)])
    uc = SendInvoice(ledger=repo, stripe=stripe, email=None, clock=lambda: NOW)  # type: ignore[arg-type]
    result = await uc.execute("inv-1")

    assert not stripe.called, "Stripe must not be called when balance_due_cents == 0"
    assert result.checkout_url is None


async def test_checkout_url_returned_when_stripe_configured() -> None:
    """When Stripe gateway is injected and balance > 0, checkout_url is returned."""

    class _FakeStripe:
        async def create_invoice_checkout_session(self, **kwargs) -> tuple[str, str]:  # type: ignore[override]
            return ("cs_test_123", "https://checkout.stripe.com/pay/test")

    stripe = _FakeStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(ledger=repo, stripe=stripe, email=None, clock=lambda: NOW)  # type: ignore[arg-type]
    result = await uc.execute("inv-1")

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    assert result.invoice.delivery_status == "sent"
