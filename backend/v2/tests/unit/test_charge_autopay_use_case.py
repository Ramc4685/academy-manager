"""Unit tests for ChargeInvoiceViaAutopay use case.

All tests use in-memory fakes — no Mongo, no real Stripe, no email.

Invariants verified:
- Happy path: open invoice + succeeded PI → LedgerPayment recorded + allocated → invoice paid
- No saved card → ValueError("no_saved_payment_method")
- Already paid → ValueError (not chargeable)
- Void → ValueError (not chargeable)
- Decline (decline_code returned) → ChargeResult(success=False), status unchanged
- Exception from gateway → ChargeResult(success=False), status unchanged
- Idempotent retry: same invoice_id → same idempotency key passed to gateway
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.domain.ledger import (
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
DUE = date(2026, 6, 30)


def _invoice(
    invoice_id: str = "inv-1",
    status: str = "open",
    balance_due_cents: int = 10_000,
    parent_id: str = "parent-1",
) -> LedgerInvoice:
    total = 10_000
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id=parent_id,
        student_id="s-1",
        period="2026-06",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=total,
        discount_cents=0,
        total_cents=total,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=DUE,
        created_at=NOW,
        updated_at=NOW,
    )


def _fake_payment(payment_id: str = "pay-1") -> LedgerPayment:
    return LedgerPayment(
        payment_id=payment_id,
        academy_id="acad-1",
        parent_id="parent-1",
        amount_cents=10_000,
        unapplied_amount_cents=0,
        currency="usd",
        status="succeeded",
        payment_method="stripe_autopay",
        stripe_payment_intent_id="pi_test",
        paid_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _paid_invoice(invoice: LedgerInvoice) -> LedgerInvoice:
    return invoice.model_copy(update={"status": "paid", "balance_due_cents": 0})


def _fake_allocation(invoice: LedgerInvoice, payment: LedgerPayment) -> LedgerAllocationResult:
    return LedgerAllocationResult(
        invoice=_paid_invoice(invoice),
        payment=payment,
        allocation=PaymentAllocation(
            allocation_id="alloc-1",
            academy_id="acad-1",
            payment_id=payment.payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=invoice.balance_due_cents,
            created_at=NOW,
        ),
    )


# ---------------------------------------------------------------------------
# Fake repos / gateways
# ---------------------------------------------------------------------------


class FakeLedgerRepo:
    def __init__(self, invoices: list[LedgerInvoice] | None = None) -> None:
        self._invoices: dict[str, LedgerInvoice] = (
            {inv.invoice_id: inv for inv in invoices} if invoices else {}
        )
        self.recorded_payments: list[tuple[LedgerPayment, str]] = []
        self.allocation_calls: list[tuple[str, str, int, str]] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list:
        return []

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        return invoice

    async def save_line(self, line) -> object:
        return line

    async def create_invoice(
        self, invoice: LedgerInvoice, *, lines: list, idempotency_key: str
    ) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        return invoice

    async def record_payment(
        self, payment: LedgerPayment, *, idempotency_key: str
    ) -> LedgerPayment:
        self.recorded_payments.append((payment, idempotency_key))
        return payment

    async def allocate_payment(
        self, *, payment_id: str, invoice_id: str, amount_cents: int, idempotency_key: str
    ) -> LedgerAllocationResult:
        self.allocation_calls.append((payment_id, invoice_id, amount_cents, idempotency_key))
        invoice = self._invoices[invoice_id]
        payment = self.recorded_payments[-1][0]
        result = _fake_allocation(invoice, payment)
        self._invoices[invoice_id] = result.invoice
        return result


class FakeStripeSucceeds:
    """Gateway that always succeeds with pi_test_123."""

    def __init__(
        self,
        customer_id: str = "cus_1",
        pm_id: str = "pm_1",
        pi_id: str = "pi_test_123",
    ) -> None:
        self.customer_id = customer_id
        self.pm_id = pm_id
        self.pi_id = pi_id
        self.lookup_calls: list[dict[str, str]] = []
        self.create_calls: list[dict] = []

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        self.lookup_calls.append({"academy_id": academy_id, "parent_id": parent_id})
        return (self.customer_id, self.pm_id)

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict,
    ) -> tuple[str, str, str | None]:
        self.create_calls.append(
            {
                "amount_cents": amount_cents,
                "currency": currency,
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
            }
        )
        return (self.pi_id, "succeeded", None)


class FakeStripeDeclines:
    """Gateway that returns a decline_code without raising."""

    def __init__(self, decline_code: str = "insufficient_funds") -> None:
        self.decline_code = decline_code

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_1")

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        return ("pi_declined", "requires_payment_method", self.decline_code)


class FakeStripeRequiresAction:
    """Gateway that returns requires_action status."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_1")

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        return ("pi_3ds", "requires_action", None)


class FakeStripeRaises:
    """Gateway that raises on PI creation (network / API error)."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_1")

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        raise RuntimeError("Stripe API unreachable")


class FakeStripeNoCard:
    """Gateway with no saved card for the parent."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return None

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        raise AssertionError("should not be called")


# ---------------------------------------------------------------------------
# Helpers to build the use case
# ---------------------------------------------------------------------------


def _uc(
    repo: FakeLedgerRepo,
    stripe: object | None = None,
) -> ChargeInvoiceViaAutopay:
    return ChargeInvoiceViaAutopay(
        ledger=repo,  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_open_invoice_pi_succeeds() -> None:
    """Open invoice + PI succeeds → LedgerPayment recorded + allocated, invoice paid."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    result = await _uc(repo, stripe).execute("inv-1")

    assert result.success is True
    assert result.invoice_id == "inv-1"
    assert result.status == "paid"
    assert result.balance_due_cents == 0
    assert result.requires_action is False
    assert result.decline_code is None

    # Exactly one payment recorded with the right idempotency key
    assert len(repo.recorded_payments) == 1
    recorded_payment, idem_key = repo.recorded_payments[0]
    assert idem_key == "autopay-pi:pi_test_123"
    assert recorded_payment.stripe_payment_intent_id == "pi_test_123"
    assert recorded_payment.amount_cents == 10_000
    assert recorded_payment.payment_method == "stripe_autopay"
    assert stripe.lookup_calls == [{"academy_id": "acad-1", "parent_id": "parent-1"}]

    # Exactly one allocation
    assert len(repo.allocation_calls) == 1
    _pay_id, inv_id, amount, alloc_key = repo.allocation_calls[0]
    assert inv_id == "inv-1"
    assert amount == 10_000
    assert alloc_key == "autopay-alloc:pi_test_123"


async def test_happy_path_partially_paid_invoice() -> None:
    """Partially paid invoice also succeeds."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="partially_paid", balance_due_cents=3_000)])
    stripe = FakeStripeSucceeds()
    result = await _uc(repo, stripe).execute("inv-1")

    assert result.success is True
    # PI is created for the balance_due_cents of the invoice at time of call
    call = stripe.create_calls[0]
    assert call["amount_cents"] == 3_000


async def test_no_saved_card_raises_value_error() -> None:
    """Parent with no saved card raises ValueError containing 'no_saved_payment_method'."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    with pytest.raises(ValueError, match="no_saved_payment_method"):
        await _uc(repo, FakeStripeNoCard()).execute("inv-1")

    # No payment should be recorded
    assert repo.recorded_payments == []


async def test_already_paid_invoice_raises_value_error() -> None:
    """Paid invoice raises ValueError (not chargeable)."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="paid", balance_due_cents=0)])
    with pytest.raises(ValueError, match="not chargeable"):
        await _uc(repo, FakeStripeSucceeds()).execute("inv-1")


async def test_charge_autopay_paid_invoice_does_not_lookup_card_or_call_stripe() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="paid", balance_due_cents=5_000)])
    stripe = FakeStripeSucceeds()

    with pytest.raises(ValueError, match="not chargeable"):
        await _uc(repo, stripe).execute("inv-1")

    assert stripe.lookup_calls == []
    assert stripe.create_calls == []


async def test_charge_autopay_zero_balance_invoice_does_not_lookup_card_or_call_stripe() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open", balance_due_cents=0)])
    stripe = FakeStripeSucceeds()

    with pytest.raises(ValueError, match="no balance due"):
        await _uc(repo, stripe).execute("inv-1")

    assert stripe.lookup_calls == []
    assert stripe.create_calls == []


async def test_charge_autopay_rechecks_invoice_before_stripe_call() -> None:
    class _StaleThenPaidLedger(FakeLedgerRepo):
        def __init__(self) -> None:
            super().__init__(invoices=[_invoice(status="open", balance_due_cents=10_000)])
            self.reads = 0

        async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
            self.reads += 1
            if self.reads == 1:
                return _invoice(status="open", balance_due_cents=10_000)
            return _invoice(status="paid", balance_due_cents=0)

    repo = _StaleThenPaidLedger()
    stripe = FakeStripeSucceeds()

    with pytest.raises(ValueError, match="no longer chargeable"):
        await _uc(repo, stripe).execute("inv-1")

    assert repo.reads == 2
    assert stripe.lookup_calls == []
    assert stripe.create_calls == []


async def test_void_invoice_raises_value_error() -> None:
    """Void invoice raises ValueError (not chargeable)."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="void", balance_due_cents=0)])
    with pytest.raises(ValueError, match="not chargeable"):
        await _uc(repo, FakeStripeSucceeds()).execute("inv-1")


async def test_draft_invoice_raises_value_error() -> None:
    """Draft invoice with zero balance raises ValueError."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="draft", balance_due_cents=0)])
    with pytest.raises(ValueError):
        await _uc(repo, FakeStripeSucceeds()).execute("inv-1")


async def test_invoice_not_found_raises_value_error() -> None:
    """Missing invoice_id raises ValueError."""
    repo = FakeLedgerRepo()
    with pytest.raises(ValueError, match="not found"):
        await _uc(repo, FakeStripeSucceeds()).execute("inv-missing")


async def test_decline_returns_charge_result_false_status_unchanged() -> None:
    """Hard decline → ChargeResult(success=False, decline_code=...), invoice status unchanged."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, FakeStripeDeclines("insufficient_funds")).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "insufficient_funds"
    assert result.status == "open"
    assert result.balance_due_cents == 10_000
    assert result.requires_action is False

    # No payment recorded, no allocation
    assert repo.recorded_payments == []
    assert repo.allocation_calls == []


async def test_stripe_exception_returns_charge_result_false() -> None:
    """Gateway raises (network/API error) → ChargeResult(success=False), status unchanged."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, FakeStripeRaises()).execute("inv-1")

    assert result.success is False
    assert result.status == "open"
    assert result.balance_due_cents == 10_000
    assert "Stripe API unreachable" in (result.decline_code or "")

    assert repo.recorded_payments == []


async def test_requires_action_returns_charge_result_false_with_flag() -> None:
    """PI requires_action (3DS) → success=False, requires_action=True, status unchanged."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, FakeStripeRequiresAction()).execute("inv-1")

    assert result.success is False
    assert result.requires_action is True
    assert result.decline_code is None
    assert result.status == "open"

    assert repo.recorded_payments == []


async def test_idempotency_key_uses_invoice_id() -> None:
    """Idempotency key passed to Stripe is deterministic: autopay-{invoice_id}."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-xyz-99", status="open")])
    stripe = FakeStripeSucceeds()
    await _uc(repo, stripe).execute("inv-xyz-99")

    call = stripe.create_calls[0]
    assert call["idempotency_key"] == "autopay-inv-xyz-99"


async def test_saved_card_lookup_uses_invoice_academy_and_parent() -> None:
    """Saved-card lookup must be scoped by invoice tenant and parent."""
    repo = FakeLedgerRepo(
        invoices=[
            _invoice(
                invoice_id="inv-academy-parent",
                status="open",
                parent_id="parent-shared-id",
            )
        ]
    )
    stripe = FakeStripeSucceeds()

    await _uc(repo, stripe).execute("inv-academy-parent")

    assert stripe.lookup_calls == [{"academy_id": "acad-1", "parent_id": "parent-shared-id"}]
    assert stripe.create_calls[0]["metadata"] == {
        "invoice_id": "inv-academy-parent",
        "academy_id": "acad-1",
        "parent_id": "parent-shared-id",
        "source": "autopay",
    }


async def test_idempotency_key_same_on_retry() -> None:
    """Calling execute twice with the same invoice_id produces the same idempotency key."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-retry", status="open")])
    stripe = FakeStripeSucceeds()
    uc = _uc(repo, stripe)

    await uc.execute("inv-retry")
    # Reset the invoice to open so the second call also passes the guard
    repo._invoices["inv-retry"] = _invoice(invoice_id="inv-retry", status="open")
    await uc.execute("inv-retry")

    keys = [call["idempotency_key"] for call in stripe.create_calls]
    assert keys[0] == keys[1] == "autopay-inv-retry"


async def test_stripe_not_configured_returns_decline() -> None:
    """When stripe=None (not configured), use case returns success=False with decline_code."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, stripe=None).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "stripe_not_configured"
    assert result.status == "open"
