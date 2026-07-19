"""Unit tests for ChargeInvoiceViaAutopay use case.

All tests use in-memory fakes — no Mongo, no real Stripe, no email.

Invariants verified:
- Happy path: open invoice + succeeded PI → LedgerPayment recorded + allocated → invoice paid
- No saved card → ValueError("no_saved_payment_method")
- Already paid → ValueError (not chargeable)
- Void → ValueError (not chargeable)
- Decline (decline_code returned) → ChargeResult(success=False), status unchanged
- Exception from gateway → ChargeResult(success=False), status unchanged
- Idempotent retry: same invoice_id/period/balance → same idempotency key passed to gateway
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
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
    enrollment_id: str | None = "enr-1",
    period: str = "2026-06",
) -> LedgerInvoice:
    total = 10_000
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id=parent_id,
        student_id="s-1",
        enrollment_id=enrollment_id,
        period=period,
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
        self.lines_by_invoice: dict[str, list[InvoiceLine]] = {}
        self.recorded_payments: list[tuple[LedgerPayment, str]] = []
        self.allocation_calls: list[tuple[str, str, int, str]] = []
        self.payment_attempts: list[dict] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return list(self.lines_by_invoice.get(invoice_id, []))

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self._invoices[invoice.invoice_id] = invoice
        return invoice

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        lines = [
            existing
            for existing in self.lines_by_invoice.get(line.invoice_id, [])
            if existing.line_id != line.line_id
        ]
        lines.append(line)
        self.lines_by_invoice[line.invoice_id] = lines
        return line

    async def delete_invoice_line(self, *, invoice_id: str, line_id: str) -> bool:
        lines = self.lines_by_invoice.get(invoice_id, [])
        kept = [line for line in lines if line.line_id != line_id]
        self.lines_by_invoice[invoice_id] = kept
        return len(kept) != len(lines)

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

    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict:
        attempt = {
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "status": status,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "stripe_checkout_session_id": stripe_checkout_session_id,
            "failure_code": failure_code,
            "failure_message": failure_message,
            "idempotency_key": idempotency_key,
            "created_by_event_id": created_by_event_id,
        }
        self.payment_attempts.append(attempt)
        return attempt

    async def allocate_payment(
        self, *, payment_id: str, invoice_id: str, amount_cents: int, idempotency_key: str
    ) -> LedgerAllocationResult:
        self.allocation_calls.append((payment_id, invoice_id, amount_cents, idempotency_key))
        invoice = self._invoices[invoice_id]
        payment = self.recorded_payments[-1][0]
        result = _fake_allocation(invoice, payment)
        self._invoices[invoice_id] = result.invoice
        return result


class FailingSaveInvoiceLedgerRepo(FakeLedgerRepo):
    def __init__(self, invoices: list[LedgerInvoice] | None = None) -> None:
        super().__init__(invoices)
        self.fail_next_save_invoice = False

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        if self.fail_next_save_invoice:
            self.fail_next_save_invoice = False
            raise ValueError("stale invoice version")
        return await super().save_invoice(invoice)


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
        self.retrieve_payment_method_calls: list[str] = []
        self.payment_method: dict = {"id": pm_id, "type": "card"}
        self.create_calls: list[dict] = []

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        self.lookup_calls.append({"academy_id": academy_id, "parent_id": parent_id})
        return (self.customer_id, self.pm_id)

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        self.retrieve_payment_method_calls.append(stripe_payment_method_id)
        return dict(self.payment_method)

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict,
        connected_account_id: str | None = None,
    ) -> tuple[str, str, str | None]:
        self.create_calls.append(
            {
                "amount_cents": amount_cents,
                "currency": currency,
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
                "connected_account_id": connected_account_id,
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

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        return {"id": stripe_payment_method_id, "type": "card"}

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        return ("pi_declined", "requires_payment_method", self.decline_code)


class FakeStripeRequiresAction:
    """Gateway that returns requires_action status."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_1")

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        return {"id": stripe_payment_method_id, "type": "card"}

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        return ("pi_3ds", "requires_action", None)


class FakeStripeProcessing:
    """Gateway that returns ACH processing status."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_bank")

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        return {"id": stripe_payment_method_id, "type": "us_bank_account"}

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        return ("pi_processing", "processing", None)


class FakeStripeRaises:
    """Gateway that raises on PI creation (network / API error)."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return ("cus_1", "pm_1")

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        return {"id": stripe_payment_method_id, "type": "card"}

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        raise RuntimeError("Stripe API unreachable")


class FakeStripeNoCard:
    """Gateway with no saved card for the parent."""

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        return None

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
        raise AssertionError("should not be called")

    async def create_off_session_payment_intent(self, **kwargs) -> tuple[str, str, str | None]:
        raise AssertionError("should not be called")


# ---------------------------------------------------------------------------
# Helpers to build the use case
# ---------------------------------------------------------------------------


class FakeEnrollmentAutopay:
    """Fake per-enrollment autopay gateway (Slice B).

    Keyed by enrollment_id. Serves the charge-eligibility gate
    (`get_autopay_enrollment_status`) and records attempt-outcome projections.
    The enrollment status is fixed here — this port never mutates it — mirroring
    the real repo's separation of enrollment lifecycle from attempt outcome.
    """

    def __init__(self, *, autopay_enrollment_status: str = "active") -> None:
        self.autopay_enrollment_status = autopay_enrollment_status
        self.recorded: list[dict] = []

    async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None:
        return self.autopay_enrollment_status

    async def record_attempt_outcome(
        self,
        *,
        enrollment_id: str,
        outcome: str,
        occurred_at,
        failure_code: str | None,
    ) -> None:
        self.recorded.append(
            {
                "enrollment_id": enrollment_id,
                "outcome": outcome,
                "occurred_at": occurred_at,
                "failure_code": failure_code,
            }
        )
        # autopay_enrollment_status is deliberately never touched here.


class FakeBillingSettingsRepo:
    def __init__(self, settings: BillingSettings) -> None:
        self.settings = settings
        self.calls = 0

    async def get(self) -> BillingSettings:
        self.calls += 1
        return self.settings


class FakeConnectedAccounts:
    def __init__(self, account: ConnectedAccount | None) -> None:
        self.account = account
        self.calls = 0

    async def get_for_academy(self) -> ConnectedAccount | None:
        self.calls += 1
        return self.account


def _seed_existing_ach_discount(repo: FakeLedgerRepo) -> None:
    existing_line = InvoiceLine(
        line_id="ach-discount:inv-1",
        academy_id="acad-1",
        invoice_id="inv-1",
        line_type="ach_discount",
        description="ACH autopay savings",
        quantity=1,
        unit_amount_cents=-250,
        amount_cents=-250,
        source_type="autopay_cash_discount",
        source_id="cash-discount-v1",
        created_at=NOW,
    )
    repo.lines_by_invoice["inv-1"] = [existing_line]
    repo._invoices["inv-1"] = repo._invoices["inv-1"].model_copy(
        update={"subtotal_cents": 9_750, "total_cents": 9_750, "balance_due_cents": 9_750}
    )


def _uc(
    repo: FakeLedgerRepo,
    stripe: object | None = None,
    enrollment_autopay: FakeEnrollmentAutopay | None = None,
    settings: FakeBillingSettingsRepo | None = None,
    connected_accounts: FakeConnectedAccounts | None = None,
) -> ChargeInvoiceViaAutopay:
    return ChargeInvoiceViaAutopay(
        ledger=repo,  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
        enrollment_autopay=enrollment_autopay,  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        connected_accounts=connected_accounts,  # type: ignore[arg-type]
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
    assert repo.payment_attempts == [
        {
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "currency": "usd",
            "status": "succeeded",
            "stripe_payment_intent_id": "pi_test_123",
            "stripe_checkout_session_id": None,
            "failure_code": None,
            "failure_message": None,
            "idempotency_key": "autopay-attempt:inv-1:2026-06:10000:succeeded:pi_test_123",
            "created_by_event_id": None,
        }
    ]

    # Exactly one allocation
    assert len(repo.allocation_calls) == 1
    _pay_id, inv_id, amount, alloc_key = repo.allocation_calls[0]
    assert inv_id == "inv-1"
    assert amount == 10_000
    assert alloc_key == "autopay-alloc:pi_test_123"


async def test_charge_routes_payment_intent_through_ready_connected_account() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    connected_account = ConnectedAccount.new(
        academy_id="acad-1",
        stripe_account_id="acct_ready",
    ).with_status(status="active", charges_enabled=True)
    connected_accounts = FakeConnectedAccounts(connected_account)

    result = await _uc(repo, stripe, connected_accounts=connected_accounts).execute("inv-1")

    assert result.success is True
    assert connected_accounts.calls == 1
    assert stripe.create_calls[0]["connected_account_id"] == "acct_ready"


async def test_charge_fails_closed_without_ready_connected_account() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    connected_accounts = FakeConnectedAccounts(
        ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_pending")
    )

    result = await _uc(repo, stripe, connected_accounts=connected_accounts).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "connected_account_not_ready"
    assert connected_accounts.calls == 1
    assert stripe.lookup_calls == []
    assert stripe.create_calls == []
    assert repo.recorded_payments == []
    assert repo.allocation_calls == []


async def test_ach_processing_records_pending_attempt_without_allocation() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, FakeStripeProcessing()).execute("inv-1")

    assert result.success is False
    assert result.invoice_id == "inv-1"
    assert result.status == "open"
    assert result.balance_due_cents == 10_000
    assert result.attempted_amount_cents == 10_000
    assert result.processing is True
    assert result.requires_action is False
    assert result.decline_code is None
    assert repo.recorded_payments == []
    assert repo.allocation_calls == []
    assert repo.payment_attempts == [
        {
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "currency": "usd",
            "status": "processing",
            "stripe_payment_intent_id": "pi_processing",
            "stripe_checkout_session_id": None,
            "failure_code": None,
            "failure_message": "ACH debit submitted; awaiting settlement.",
            "idempotency_key": "autopay-attempt:inv-1:2026-06:10000:processing:pi_processing",
            "created_by_event_id": None,
        }
    ]


async def test_ach_payment_method_adds_discount_line_before_charge_amount_and_key() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
            ach_discount_label="ACH autopay savings",
            disclosure_version="cash-discount-v1",
        )
    )

    result = await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert result.success is True
    assert result.attempted_amount_cents == 9_750
    assert stripe.retrieve_payment_method_calls == ["pm_1"]
    assert stripe.create_calls[0]["amount_cents"] == 9_750
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:9750"
    assert stripe.create_calls[0]["metadata"]["disclosure_version"] == "cash-discount-v1"
    assert repo.payment_attempts[0]["amount_cents"] == 9_750
    assert repo.recorded_payments[0][0].amount_cents == 9_750
    assert repo.recorded_payments[0][0].metadata == {
        "ach_discount_cents": "250",
        "ach_discount_line_id": "ach-discount:inv-1",
        "ach_discount_percent": "2.5",
        "disclosure_version": "cash-discount-v1",
        "funding_type": "us_bank_account",
        "funding_type_source": "server_payment_method",
    }
    assert repo.allocation_calls[0][2] == 9_750
    discount_lines = [
        line for line in repo.lines_by_invoice["inv-1"] if line.line_type == "ach_discount"
    ]
    assert len(discount_lines) == 1
    assert discount_lines[0].line_id == "ach-discount:inv-1"
    assert discount_lines[0].description == "ACH autopay savings"
    assert discount_lines[0].amount_cents == -250
    assert discount_lines[0].source_type == "autopay_cash_discount"
    assert discount_lines[0].source_id == "cash-discount-v1"


async def test_ach_discount_new_line_rolls_back_when_invoice_save_fails() -> None:
    repo = FailingSaveInvoiceLedgerRepo(invoices=[_invoice(status="open")])
    repo.fail_next_save_invoice = True
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
            ach_discount_label="ACH autopay savings",
            disclosure_version="cash-discount-v1",
        )
    )

    with pytest.raises(ValueError, match="stale invoice version"):
        await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert repo.lines_by_invoice["inv-1"] == []
    assert stripe.create_calls == []


async def test_ach_discount_existing_line_is_restored_when_invoice_save_fails() -> None:
    repo = FailingSaveInvoiceLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    original_line = repo.lines_by_invoice["inv-1"][0]
    repo.fail_next_save_invoice = True
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "card", "card": {"funding": "credit"}}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
            ach_discount_label="ACH autopay savings",
            disclosure_version="cash-discount-v1",
        )
    )

    with pytest.raises(ValueError, match="stale invoice version"):
        await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert repo.lines_by_invoice["inv-1"] == [original_line]
    assert stripe.create_calls == []


@pytest.mark.parametrize("funding_type", ["credit", "debit", "prepaid"])
async def test_saved_card_payment_method_funding_does_not_add_discount_or_fee(
    funding_type: str,
) -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "card", "card": {"funding": funding_type}}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert repo.lines_by_invoice.get("inv-1", []) == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:10000"
    assert "ach_discount_cents" not in stripe.create_calls[0]["metadata"]
    assert "processing_fee_cents" not in stripe.create_calls[0]["metadata"]
    assert "payment_method_fee_cents" not in stripe.create_calls[0]["metadata"]
    assert repo.recorded_payments[0][0].metadata is None


async def test_no_settings_repo_fails_safe_to_no_discount_even_for_ach() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}

    await _uc(repo, stripe, settings=None).execute("inv-1")

    assert repo.lines_by_invoice.get("inv-1", []) == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000


async def test_unknown_payment_method_type_fails_safe_to_no_discount() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "cashapp"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert repo.lines_by_invoice.get("inv-1", []) == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000


async def test_retrieve_payment_method_failure_fails_safe_to_no_discount() -> None:
    class StripeRetrieveFails(FakeStripeSucceeds):
        async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
            self.retrieve_payment_method_calls.append(stripe_payment_method_id)
            raise RuntimeError("stripe retrieve unavailable")

    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = StripeRetrieveFails()
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert stripe.retrieve_payment_method_calls == ["pm_1"]
    assert repo.lines_by_invoice.get("inv-1", []) == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000


async def test_existing_ach_discount_is_removed_when_current_payment_method_is_card() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "card", "card": {"funding": "credit"}}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert [line.line_type for line in repo.lines_by_invoice["inv-1"]] == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:10000"


async def test_existing_ach_discount_is_removed_when_payment_method_retrieve_fails() -> None:
    class StripeRetrieveFails(FakeStripeSucceeds):
        async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict:
            self.retrieve_payment_method_calls.append(stripe_payment_method_id)
            raise RuntimeError("stripe retrieve unavailable")

    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    stripe = StripeRetrieveFails()
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert [line.line_type for line in repo.lines_by_invoice["inv-1"]] == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:10000"


async def test_existing_ach_discount_is_removed_when_settings_are_disabled() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=False,
            ach_discount_percent=2.5,
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert [line.line_type for line in repo.lines_by_invoice["inv-1"]] == []
    assert stripe.create_calls[0]["amount_cents"] == 10_000
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:10000"


async def test_repeated_ach_charge_does_not_duplicate_existing_discount_line() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    existing_line = repo.lines_by_invoice["inv-1"][0]
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=2.5,
            ach_discount_label="ACH autopay savings",
            disclosure_version="cash-discount-v1",
        )
    )

    await _uc(repo, stripe, settings=settings).execute("inv-1")

    discount_lines = [
        line for line in repo.lines_by_invoice["inv-1"] if line.line_type == "ach_discount"
    ]
    assert discount_lines == [existing_line]
    assert stripe.create_calls[0]["amount_cents"] == 9_750
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:9750"


async def test_existing_ach_discount_is_reconciled_when_current_settings_change() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    _seed_existing_ach_discount(repo)
    stripe = FakeStripeSucceeds()
    stripe.payment_method = {"id": "pm_1", "type": "us_bank_account"}
    settings = FakeBillingSettingsRepo(
        BillingSettings(
            academy_id="acad-1",
            ach_discount_enabled=True,
            ach_discount_percent=3.0,
            ach_discount_label="Updated ACH savings",
            disclosure_version="cash-discount-v2",
        )
    )

    result = await _uc(repo, stripe, settings=settings).execute("inv-1")

    assert result.success is True
    discount_lines = [
        line for line in repo.lines_by_invoice["inv-1"] if line.line_type == "ach_discount"
    ]
    assert len(discount_lines) == 1
    assert discount_lines[0].line_id == "ach-discount:inv-1"
    assert discount_lines[0].description == "Updated ACH savings"
    assert discount_lines[0].amount_cents == -300
    assert discount_lines[0].unit_amount_cents == -300
    assert discount_lines[0].source_id == "cash-discount-v2"
    assert stripe.create_calls[0]["amount_cents"] == 9_700
    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-1:2026-06:9700"
    assert stripe.create_calls[0]["metadata"]["ach_discount_cents"] == "300"
    assert stripe.create_calls[0]["metadata"]["disclosure_version"] == "cash-discount-v2"
    recorded_payment = repo.recorded_payments[0][0]
    assert recorded_payment.amount_cents == 9_700
    assert recorded_payment.metadata == {
        "ach_discount_cents": "300",
        "ach_discount_line_id": "ach-discount:inv-1",
        "ach_discount_percent": "3.0",
        "disclosure_version": "cash-discount-v2",
        "funding_type": "us_bank_account",
        "funding_type_source": "server_payment_method",
    }
    assert repo.allocation_calls[0][2] == 9_700


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
    assert repo.payment_attempts == [
        {
            "invoice_id": "inv-1",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "currency": "usd",
            "status": "failed",
            "stripe_payment_intent_id": "pi_declined",
            "stripe_checkout_session_id": None,
            "failure_code": "insufficient_funds",
            "failure_message": "insufficient_funds",
            "idempotency_key": "autopay-attempt:inv-1:2026-06:10000:failed:pi_declined",
            "created_by_event_id": None,
        }
    ]


async def test_paused_enrollment_invoice_is_not_charged() -> None:
    """Security P2: an invoice whose enrollment is paused must NOT be
    auto-charged — no Stripe call, no attempt recorded — and the result carries
    the autopay_not_active decline code."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="paused")
    stripe = FakeStripeSucceeds()

    result = await _uc(repo, stripe, enrollment_autopay=enrollment_autopay).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "autopay_not_active"
    assert result.status == "open"
    assert result.balance_due_cents == 10_000
    # No charge attempted, no ledger writes, no attempt-outcome projection.
    assert stripe.create_calls == []
    assert stripe.lookup_calls == []
    assert repo.recorded_payments == []
    assert repo.payment_attempts == []
    assert enrollment_autopay.recorded == []


async def test_disabled_enrollment_invoice_is_not_charged() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="disabled")
    stripe = FakeStripeSucceeds()

    result = await _uc(repo, stripe, enrollment_autopay=enrollment_autopay).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "autopay_not_active"
    assert stripe.create_calls == []
    assert repo.payment_attempts == []


async def test_invoice_without_enrollment_id_fails_closed_and_is_not_charged() -> None:
    """P2: the eligibility gate is fail-CLOSED. An autopay invoice with a
    null/empty enrollment_id cannot be resolved to an autopay status, so it must
    be declined (autopay_not_active) — never charged by bypassing the check."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open", enrollment_id=None)])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="active")
    stripe = FakeStripeSucceeds()

    result = await _uc(repo, stripe, enrollment_autopay=enrollment_autopay).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "autopay_not_active"
    assert result.status == "open"
    assert result.balance_due_cents == 10_000
    # No Stripe call, no ledger writes, and the status lookup was never reached.
    assert stripe.create_calls == []
    assert stripe.lookup_calls == []
    assert repo.recorded_payments == []
    assert repo.payment_attempts == []
    assert enrollment_autopay.recorded == []


async def test_bounced_charge_sets_declined_outcome_but_leaves_enrollment_active() -> None:
    """Regression (Slice B): a bounced autopay charge projects
    last_attempt_outcome=declined onto the enrollment but does NOT change
    autopay_enrollment_status — the enrollment is still enrolled in autopay,
    only the last attempt failed."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="active")

    result = await _uc(
        repo,
        FakeStripeDeclines("insufficient_funds"),
        enrollment_autopay=enrollment_autopay,
    ).execute("inv-1")

    assert result.success is False
    assert enrollment_autopay.recorded == [
        {
            "enrollment_id": "enr-1",
            "outcome": "declined",
            "occurred_at": NOW,
            "failure_code": "insufficient_funds",
        }
    ]
    # Enrollment axis untouched by the attempt-outcome projection.
    assert enrollment_autopay.autopay_enrollment_status == "active"


async def test_successful_charge_projects_succeeded_outcome() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="active")

    await _uc(repo, FakeStripeSucceeds(), enrollment_autopay=enrollment_autopay).execute("inv-1")

    assert enrollment_autopay.recorded == [
        {
            "enrollment_id": "enr-1",
            "outcome": "succeeded",
            "occurred_at": NOW,
            "failure_code": None,
        }
    ]
    assert enrollment_autopay.autopay_enrollment_status == "active"


async def test_requires_action_projects_requires_action_outcome() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    enrollment_autopay = FakeEnrollmentAutopay(autopay_enrollment_status="active")

    await _uc(repo, FakeStripeRequiresAction(), enrollment_autopay=enrollment_autopay).execute(
        "inv-1"
    )

    assert enrollment_autopay.recorded == [
        {
            "enrollment_id": "enr-1",
            "outcome": "requires_action",
            "occurred_at": NOW,
            "failure_code": None,
        }
    ]


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


async def test_idempotency_key_uses_invoice_id_period_and_balance_due() -> None:
    """Stripe PI idempotency key is scoped by invoice, period, and attempted amount."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-xyz-99", status="open")])
    stripe = FakeStripeSucceeds()
    await _uc(repo, stripe).execute("inv-xyz-99")

    call = stripe.create_calls[0]
    assert call["idempotency_key"] == "autopay:inv-xyz-99:2026-06:10000"


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


async def test_admin_charge_source_and_actor_are_recorded_in_stripe_metadata() -> None:
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-admin", status="open")])
    stripe = FakeStripeSucceeds()

    await _uc(repo, stripe).execute(
        "inv-admin",
        source="admin_billing_setup",
        actor_id="admin-1",
    )

    metadata = stripe.create_calls[0]["metadata"]
    assert metadata["source"] == "admin_billing_setup"
    assert metadata["actor_id"] == "admin-1"


async def test_idempotency_key_same_on_retry_with_same_period_and_balance() -> None:
    """A true replay for the same invoice, period, and balance reuses the same PI key."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-retry", status="open")])
    stripe = FakeStripeSucceeds()
    uc = _uc(repo, stripe)

    await uc.execute("inv-retry")
    # Reset the invoice to open so the second call also passes the guard
    repo._invoices["inv-retry"] = _invoice(invoice_id="inv-retry", status="open")
    await uc.execute("inv-retry")

    keys = [call["idempotency_key"] for call in stripe.create_calls]
    assert keys[0] == keys[1] == "autopay:inv-retry:2026-06:10000"


async def test_default_idempotency_key_remains_slice_c_shape_without_retry_scope() -> None:
    repo = FakeLedgerRepo([_invoice("inv-default-scope")])
    stripe = FakeStripeSucceeds()

    await _uc(repo, stripe).execute("inv-default-scope")

    assert stripe.create_calls[0]["idempotency_key"] == "autopay:inv-default-scope:2026-06:10000"
    assert repo.payment_attempts[0]["idempotency_key"] == (
        "autopay-attempt:inv-default-scope:2026-06:10000:" "succeeded:pi_test_123"
    )


async def test_dunning_retry_scope_changes_pi_and_attempt_idempotency_keys() -> None:
    repo = FakeLedgerRepo([_invoice("inv-dunning-scope")])
    stripe = FakeStripeSucceeds()
    uc = _uc(repo, stripe)

    await uc.execute("inv-dunning-scope", retry_scope="dunning-attempt:1")
    repo._invoices["inv-dunning-scope"] = _invoice("inv-dunning-scope")
    stripe.pi_id = "pi_test_456"
    await uc.execute("inv-dunning-scope", retry_scope="dunning-attempt:2")

    assert [call["idempotency_key"] for call in stripe.create_calls] == [
        "autopay:inv-dunning-scope:2026-06:10000:dunning-attempt:1",
        "autopay:inv-dunning-scope:2026-06:10000:dunning-attempt:2",
    ]
    assert [attempt["idempotency_key"] for attempt in repo.payment_attempts] == [
        "autopay-attempt:inv-dunning-scope:2026-06:10000:"
        "dunning-attempt:1:succeeded:pi_test_123",
        "autopay-attempt:inv-dunning-scope:2026-06:10000:"
        "dunning-attempt:2:succeeded:pi_test_456",
    ]


async def test_idempotency_key_changes_when_balance_due_changes() -> None:
    """Same invoice and period with a changed balance must create a new PI key and amount."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-balance", status="open")])
    stripe = FakeStripeSucceeds()
    uc = _uc(repo, stripe)

    await uc.execute("inv-balance")
    repo._invoices["inv-balance"] = _invoice(
        invoice_id="inv-balance",
        status="open",
        balance_due_cents=6_500,
    )
    await uc.execute("inv-balance")

    assert [call["idempotency_key"] for call in stripe.create_calls] == [
        "autopay:inv-balance:2026-06:10000",
        "autopay:inv-balance:2026-06:6500",
    ]
    assert [call["amount_cents"] for call in stripe.create_calls] == [10_000, 6_500]


async def test_idempotency_key_changes_when_invoice_period_changes() -> None:
    """Same invoice and balance in a new billing period must create a new PI key."""
    repo = FakeLedgerRepo(invoices=[_invoice(invoice_id="inv-period", status="open")])
    stripe = FakeStripeSucceeds()
    uc = _uc(repo, stripe)

    await uc.execute("inv-period")
    repo._invoices["inv-period"] = _invoice(
        invoice_id="inv-period",
        status="open",
        period="2026-07",
    )
    await uc.execute("inv-period")

    assert [call["idempotency_key"] for call in stripe.create_calls] == [
        "autopay:inv-period:2026-06:10000",
        "autopay:inv-period:2026-07:10000",
    ]


async def test_stripe_exception_failed_attempt_key_includes_period_amount_and_status() -> None:
    """Stripe-error attempts are scoped so different amount attempts do not collapse."""
    repo = FakeLedgerRepo(
        invoices=[
            _invoice(
                invoice_id="inv-stripe-error",
                status="open",
                balance_due_cents=7_500,
                period="2026-07",
            )
        ]
    )

    await _uc(repo, FakeStripeRaises()).execute("inv-stripe-error")

    assert repo.payment_attempts[0]["idempotency_key"] == (
        "autopay-attempt:inv-stripe-error:2026-07:7500:failed:stripe-error"
    )


async def test_stripe_not_configured_returns_decline() -> None:
    """When stripe=None (not configured), use case returns success=False with decline_code."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    result = await _uc(repo, stripe=None).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "stripe_not_configured"
    assert result.status == "open"


# ---------------------------------------------------------------------------
# allow_platform_charge_fallback (temporary Connect-review escape hatch)
# ---------------------------------------------------------------------------


async def test_platform_fallback_enabled_charges_via_platform_when_account_not_ready() -> None:
    """Flag on + connected account not ready → charge proceeds with connected_account_id=None."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    connected_accounts = FakeConnectedAccounts(
        ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_pending")
    )
    settings = FakeBillingSettingsRepo(
        BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=True)
    )

    result = await _uc(
        repo, stripe, settings=settings, connected_accounts=connected_accounts
    ).execute("inv-1")

    assert result.success is True
    assert result.decline_code is None
    assert stripe.create_calls[0]["connected_account_id"] is None
    assert connected_accounts.calls == 1


async def test_platform_fallback_disabled_still_declines_when_account_not_ready() -> None:
    """Flag off (default) + connected account not ready → still declines as today."""
    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    connected_accounts = FakeConnectedAccounts(
        ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_pending")
    )
    settings = FakeBillingSettingsRepo(
        BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=False)
    )

    result = await _uc(
        repo, stripe, settings=settings, connected_accounts=connected_accounts
    ).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "connected_account_not_ready"
    assert stripe.create_calls == []


async def test_platform_fallback_settings_lookup_failure_fails_closed_to_decline() -> None:
    """Settings lookup raises + account not ready → still declines (fail closed)."""

    class RaisingSettingsRepo:
        async def get(self) -> BillingSettings:
            raise RuntimeError("settings store unavailable")

    repo = FakeLedgerRepo(invoices=[_invoice(status="open")])
    stripe = FakeStripeSucceeds()
    connected_accounts = FakeConnectedAccounts(
        ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_pending")
    )

    result = await _uc(
        repo,
        stripe,
        settings=RaisingSettingsRepo(),  # type: ignore[arg-type]
        connected_accounts=connected_accounts,
    ).execute("inv-1")

    assert result.success is False
    assert result.decline_code == "connected_account_not_ready"
    assert stripe.create_calls == []
