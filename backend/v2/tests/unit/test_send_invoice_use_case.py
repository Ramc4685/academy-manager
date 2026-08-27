"""Unit tests for SendInvoice use case (in-memory fake, no Mongo, no Stripe, no email).

Key invariant: financial status is NEVER changed by SendInvoice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
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
    enrollment_id: str | None = None,
    email_provider_message_id: str | None = None,
) -> LedgerInvoice:
    total = 10_000
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="s-1",
        enrollment_id=enrollment_id,
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
        email_provider_message_id=email_provider_message_id,
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
        self.payment_attempts: list[dict] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self._invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [ln for ln in self._lines.values() if ln.invoice_id == invoice_id]

    async def list_invoices_for_student(
        self, student_id: str, *, limit: int = 100
    ) -> list[LedgerInvoice]:
        return [inv for inv in self._invoices.values() if inv.student_id == student_id][:limit]

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

    async def record_payment_attempt(self, **kwargs) -> dict:
        # Mirrors the Mongo repo's idempotency: same key → same row, no dupes.
        for existing in self.payment_attempts:
            if existing["idempotency_key"] == kwargs["idempotency_key"]:
                return existing
        self.payment_attempts.append(kwargs)
        return kwargs


class FakeInvoiceEmail:
    def __init__(self, *, fail: bool = False, message_id: str | None = "re_test_1") -> None:
        self.fail = fail
        self.message_id = message_id
        self.calls: list[dict] = []

    async def send_invoice_email(self, **kwargs) -> str | None:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("email provider unavailable")
        return self.message_id


class FakeInvoiceStripe:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_invoice_checkout_session(self, **kwargs) -> tuple[str, str]:
        self.calls.append(kwargs)
        return ("cs_test_123", "https://checkout.stripe.com/pay/test")


class _StubConnectedAccount:
    def __init__(self, *, ready: bool, stripe_account_id: str = "acct_ready_1") -> None:
        self._ready = ready
        self.stripe_account_id = stripe_account_id

    def is_ready_for_charges(self) -> bool:
        return self._ready


class _FakeConnectedAccounts:
    def __init__(self, account: _StubConnectedAccount | None) -> None:
        self._account = account

    async def get_for_academy(self):
        return self._account


class _FakeBillingSettings:
    def __init__(self, settings: BillingSettings) -> None:
        self._settings = settings

    async def get(self) -> BillingSettings:
        return self._settings


class _RaisingBillingSettings:
    async def get(self) -> BillingSettings:
        raise RuntimeError("settings store unavailable")


# ---------------------------------------------------------------------------
# Use-case factory
# ---------------------------------------------------------------------------


def _uc(repo: FakeLedgerRepository, *, email: FakeInvoiceEmail | None = None) -> SendInvoice:
    return SendInvoice(ledger=repo, stripe=None, email=email, clock=lambda: NOW)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_send_draft_invoice_finalizes_then_records_delivery_after_email() -> None:
    """Draft invoice: finalized first (status→open), then successful email records delivery."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="draft")])
    email = FakeInvoiceEmail()
    result = await _uc(repo, email=email).execute("inv-1")

    assert result.invoice.status == "open", "financial status must be 'open' after finalize+send"
    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == NOW
    assert result.invoice.last_sent_at == NOW
    assert email.calls == [
        {
            "parent_id": "parent-1",
            "invoice_id": "inv-1",
            "period": "2026-06",
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "currency": "usd",
            "checkout_url": None,
        }
    ]


async def test_successful_send_persists_provider_message_id() -> None:
    """Resend's provider message id is stored on the invoice for deep-linking."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open")])
    result = await _uc(repo, email=FakeInvoiceEmail(message_id="re_abc123")).execute("inv-1")

    assert result.invoice.email_provider_message_id == "re_abc123"


async def test_send_without_provider_id_leaves_field_none() -> None:
    """A provider that returns no id (or a stub) leaves the field unset."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open")])
    result = await _uc(repo, email=FakeInvoiceEmail(message_id=None)).execute("inv-1")

    assert result.invoice.delivery_status == "sent"
    assert result.invoice.email_provider_message_id is None


async def test_failed_send_preserves_previous_provider_message_id() -> None:
    """A later failed send must not wipe the last good Resend id (link stays valid)."""
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="open", email_provider_message_id="re_first")]
    )
    result = await _uc(repo, email=FakeInvoiceEmail(fail=True)).execute("inv-1")

    assert result.invoice.delivery_status == "delivery_failed"
    assert result.invoice.email_provider_message_id == "re_first"


async def test_send_open_invoice_records_delivery_without_changing_status() -> None:
    """Open invoice: delivery recorded, financial status remains 'open'."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open")])
    result = await _uc(repo, email=FakeInvoiceEmail()).execute("inv-1")

    assert result.invoice.status == "open"
    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == NOW
    assert result.invoice.last_sent_at == NOW


async def test_send_partially_paid_invoice_keeps_status() -> None:
    """Partially paid invoice: delivery recorded, financial status stays 'partially_paid'."""
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="partially_paid", balance_due_cents=3_000)]
    )
    result = await _uc(repo, email=FakeInvoiceEmail()).execute("inv-1")

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
    result = await _uc(repo, email=FakeInvoiceEmail()).execute("inv-1")

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
        result = await _uc(repo, email=FakeInvoiceEmail()).execute("inv-1")
        assert result.invoice.status == expected_status, (
            f"financial status changed from {initial_status!r} to {result.invoice.status!r}"
        )


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
    assert result.invoice.delivery_status == "not_sent"
    assert result.invoice.sent_at is None
    assert result.invoice.last_sent_at is None


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


async def test_send_invoice_skips_checkout_for_paid_invoice_even_with_positive_balance() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="paid", balance_due_cents=5_000)])
    uc = SendInvoice(ledger=repo, stripe=stripe, email=None, clock=lambda: NOW)

    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_send_invoice_skips_checkout_for_void_invoice_even_with_positive_balance() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="void", balance_due_cents=5_000)])
    uc = SendInvoice(ledger=repo, stripe=stripe, email=None, clock=lambda: NOW)

    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_checkout_refused_when_connected_accounts_not_configured() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(ledger=repo, stripe=stripe, email=None, clock=lambda: NOW)
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_checkout_url_is_passed_to_successful_email_before_marking_sent() -> None:
    stripe = FakeInvoiceStripe()
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    assert stripe.calls[0]["connected_account_id"] == "acct_ready_1"
    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == NOW
    assert email.calls[0]["checkout_url"] == "https://checkout.stripe.com/pay/test"


async def test_checkout_routes_destination_charge_when_connected_account_ready() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    assert stripe.calls[0]["connected_account_id"] == "acct_ready_1"


async def test_checkout_refused_when_connected_account_not_ready() -> None:
    """Repo wired but account not charge-ready: no platform-charge pay link is minted."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_checkout_refused_when_connected_account_missing() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(None),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_execute_with_enroll_autopay_requests_saved_payment_method() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="open", balance_due_cents=10_000, enrollment_id="enroll-1")]
    )
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1", enroll_autopay=True)

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    call = stripe.calls[0]
    assert call["save_payment_method_for_autopay"] is True
    assert call["autopay_enrollment_ids"] == ["enroll-1"]
    # A distinct idempotency key: an earlier one-time pay link for the same
    # balance must not be replayed without the saved-payment-method params.
    assert call["idempotency_key"] == "invoice-checkout:inv-1:10000:autopay-optin"
    # Destination-charge routing is unchanged by the opt-in flag.
    assert call["connected_account_id"] == "acct_ready_1"


async def test_execute_with_enroll_autopay_and_no_enrollment_id_sends_empty_ids() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    await uc.execute("inv-1", enroll_autopay=True)

    call = stripe.calls[0]
    assert call["save_payment_method_for_autopay"] is True
    assert call["autopay_enrollment_ids"] == []


async def test_execute_default_keeps_gateway_call_unchanged() -> None:
    """Without enroll_autopay the gateway call carries none of the new kwargs
    and the historical idempotency key — SendInvoice email flow stays as-is."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="open", balance_due_cents=10_000, enrollment_id="enroll-1")]
    )
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    await uc.execute("inv-1")

    call = stripe.calls[0]
    assert "save_payment_method_for_autopay" not in call
    assert "autopay_enrollment_ids" not in call
    assert call["idempotency_key"] == "invoice-checkout:inv-1:10000"


async def test_email_failure_records_delivery_failed_without_sent_at() -> None:
    email = FakeInvoiceEmail(fail=True)
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    result = await _uc(repo, email=email).execute("inv-1")

    assert result.invoice.delivery_status == "delivery_failed"
    assert result.invoice.sent_at is None
    assert result.invoice.last_sent_at == NOW


# ---------------------------------------------------------------------------
# allow_platform_charge_fallback (temporary Connect-review escape hatch)
# ---------------------------------------------------------------------------


async def test_platform_fallback_enabled_mints_pay_link_with_platform_charge() -> None:
    """Flag on + account not ready → pay link minted with connected_account_id=None."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=True)
        ),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    assert stripe.calls[0]["connected_account_id"] is None


async def test_platform_fallback_disabled_still_blocks_when_account_not_ready() -> None:
    """Flag off (default) + account not ready → still blocked as today."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=False)
        ),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


async def test_platform_fallback_settings_lookup_failure_fails_closed() -> None:
    """Settings lookup raises + account not ready → still blocked (fail closed)."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        settings=_RaisingBillingSettings(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert result.checkout_url is None


# ---------------------------------------------------------------------------
# bundle_student_balance — the admin "Send" link should cover every unpaid
# invoice for the student, not just the one clicked.
# ---------------------------------------------------------------------------


def _uc_with_stripe(repo: FakeLedgerRepository, stripe: FakeInvoiceStripe) -> SendInvoice:
    return SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


async def test_bundle_student_balance_covers_all_open_invoices_for_student() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(invoice_id="inv-1", status="open", balance_due_cents=7_000),
            _invoice(invoice_id="inv-2", status="open", balance_due_cents=7_000),
            _invoice(invoice_id="inv-3", status="open", balance_due_cents=7_000),
        ]
    )
    uc = _uc_with_stripe(repo, stripe)

    result = await uc.execute("inv-1", bundle_student_balance=True)

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    call = stripe.calls[0]
    assert call["amount_cents"] == 21_000
    assert call["metadata"]["invoice_ids"] == "inv-1,inv-2,inv-3"
    assert call["metadata"]["type"] == "balance_payment"
    assert call["metadata"]["source"] == "invoice_balance"
    assert "invoice_id" not in call["metadata"]


async def test_bundle_student_balance_noop_when_only_one_payable_invoice() -> None:
    """Single unpaid invoice: identical gateway call to the non-bundled path."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = _uc_with_stripe(repo, stripe)

    result = await uc.execute("inv-1", bundle_student_balance=True)

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    call = stripe.calls[0]
    assert call["amount_cents"] == 10_000
    assert call["metadata"]["invoice_id"] == "inv-1"
    assert call["metadata"]["source"] == "invoice_pay_link"
    assert call["idempotency_key"] == "invoice-checkout:inv-1:10000"


async def test_bundle_student_balance_excludes_other_students_invoices() -> None:
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(invoice_id="inv-1", status="open", balance_due_cents=7_000),
            _invoice(
                invoice_id="inv-other-student",
                status="open",
                balance_due_cents=9_000,
            ),
        ]
    )
    repo._invoices["inv-other-student"] = repo._invoices["inv-other-student"].model_copy(
        update={"student_id": "s-2"}
    )
    uc = _uc_with_stripe(repo, stripe)

    result = await uc.execute("inv-1", bundle_student_balance=True)

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    call = stripe.calls[0]
    assert call["amount_cents"] == 7_000
    assert call["metadata"]["invoice_id"] == "inv-1"


async def test_bundle_student_balance_email_reflects_combined_balance() -> None:
    stripe = FakeInvoiceStripe()
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(invoice_id="inv-1", status="open", balance_due_cents=7_000),
            _invoice(invoice_id="inv-2", status="open", balance_due_cents=7_000),
        ]
    )
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    await uc.execute("inv-1", bundle_student_balance=True)

    assert email.calls[0]["balance_due_cents"] == 14_000
    assert email.calls[0]["total_cents"] == 20_000


async def test_bundle_student_balance_ignored_when_not_requested() -> None:
    """Without the flag (parent's own single-invoice pay), behavior is unchanged."""
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(invoice_id="inv-1", status="open", balance_due_cents=7_000),
            _invoice(invoice_id="inv-2", status="open", balance_due_cents=7_000),
        ]
    )
    uc = _uc_with_stripe(repo, stripe)

    result = await uc.execute("inv-1")

    assert result.checkout_url == "https://checkout.stripe.com/pay/test"
    call = stripe.calls[0]
    assert call["amount_cents"] == 7_000
    assert call["metadata"]["invoice_id"] == "inv-1"


# ---------------------------------------------------------------------------
# issue #426 — checkout-creation failures must be loud, not swallowed
#
# The bug: any Stripe exception (and the connected-account-blocked path) set
# checkout_url=None, logged WARNING, and STILL emailed the parent an invoice
# saying "contact the academy to arrange payment", recorded delivery_status
# "sent". A broken payment setup looked like a successful send.
# ---------------------------------------------------------------------------


class _RaisingInvoiceStripe:
    """Gateway whose checkout creation always fails (e.g. the idempotency-key
    parameter-mismatch failure mode that deterministically re-fails on retry)."""

    def __init__(self, message: str = "idempotency key reused with different params") -> None:
        self.message = message
        self.calls: list[dict] = []

    async def create_invoice_checkout_session(self, **kwargs) -> tuple[str, str]:
        self.calls.append(kwargs)
        raise RuntimeError(self.message)


def _blocked_uc(
    repo: FakeLedgerRepository,
    *,
    email: FakeInvoiceEmail | None,
) -> SendInvoice:
    """Connected account present but not charge-ready, fallback flag off."""
    return SendInvoice(
        ledger=repo,
        stripe=FakeInvoiceStripe(),
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=False)
        ),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


async def test_stripe_exception_does_not_send_parent_email() -> None:
    """Stripe raised → the parent gets NO email and delivery is not 'sent'."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe(),  # type: ignore[arg-type]
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert email.calls == [], "no dead-end invoice email may be sent"
    assert result.checkout_url is None
    assert result.invoice.delivery_status == "delivery_failed"
    assert result.invoice.sent_at is None


async def test_stripe_exception_returns_distinct_failure_code() -> None:
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe(),  # type: ignore[arg-type]
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert result.checkout_failure_code == "checkout_creation_failed"


async def test_stripe_exception_records_failed_payment_attempt() -> None:
    """The failure lands on the same telemetry axis autopay declines use."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe("card gateway exploded"),  # type: ignore[arg-type]
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    await uc.execute("inv-1")

    assert len(repo.payment_attempts) == 1
    attempt = repo.payment_attempts[0]
    # NOT "failed": that status means a charge outcome and would contaminate
    # the dunning sweep and the billing-health failed-payments list.
    assert attempt["status"] == "checkout_mint_failed"
    assert attempt["failure_code"] == "checkout_creation_failed"
    assert attempt["failure_message"] == "card gateway exploded"
    assert attempt["invoice_id"] == "inv-1"
    assert attempt["parent_id"] == "parent-1"
    assert attempt["amount_cents"] == 10_000
    assert attempt["currency"] == "usd"
    assert attempt["stripe_payment_intent_id"] is None
    assert attempt["stripe_checkout_session_id"] is None


async def test_repeated_identical_checkout_failure_is_idempotent() -> None:
    """Re-sending the same failing invoice must not spam payment_attempts."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe(),  # type: ignore[arg-type]
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    await uc.execute("inv-1")
    await uc.execute("inv-1")

    assert len(repo.payment_attempts) == 1


async def test_connected_account_blocked_with_fallback_off_suppresses_email() -> None:
    """The blocked path produced the identical dead-end email — it must not."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    result = await _blocked_uc(repo, email=email).execute("inv-1")

    assert email.calls == []
    assert result.checkout_url is None
    assert result.checkout_failure_code == "connected_account_not_ready"
    assert result.invoice.delivery_status == "delivery_failed"
    assert result.invoice.sent_at is None


async def test_connected_account_blocked_records_failed_payment_attempt() -> None:
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    await _blocked_uc(repo, email=None).execute("inv-1")

    assert len(repo.payment_attempts) == 1
    assert repo.payment_attempts[0]["status"] == "checkout_mint_failed"
    assert repo.payment_attempts[0]["failure_code"] == "connected_account_not_ready"


async def test_connected_accounts_not_configured_records_distinct_code() -> None:
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(ledger=repo, stripe=FakeInvoiceStripe(), email=None, clock=lambda: NOW)
    result = await uc.execute("inv-1")

    assert result.checkout_failure_code == "connected_accounts_not_configured"
    assert repo.payment_attempts[0]["failure_code"] == "connected_accounts_not_configured"


async def test_settings_lookup_failure_still_fails_closed_and_loudly() -> None:
    """Fail-closed invariant preserved: blocked AND recorded, not silently sent."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    stripe = FakeInvoiceStripe()
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),  # type: ignore[arg-type]
        settings=_RaisingBillingSettings(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == []
    assert email.calls == []
    assert result.checkout_failure_code == "connected_account_not_ready"


async def test_no_stripe_configured_still_sends_contact_the_academy_email() -> None:
    """A genuinely Stripe-less academy is NOT a failure — that email still goes
    out with checkout_url=None, which renders the 'contact the academy to
    arrange payment' copy. Only errors/blocks are suppressed."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    result = await _uc(repo, email=email).execute("inv-1")

    assert len(email.calls) == 1
    assert email.calls[0]["checkout_url"] is None
    assert result.invoice.delivery_status == "sent"
    assert result.checkout_failure_code is None
    assert repo.payment_attempts == []


async def test_zero_balance_invoice_still_sends_email_without_failure_code() -> None:
    """Nothing to pay → no pay link needed → normal email, no failure recorded."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="paid", balance_due_cents=0)])
    uc = SendInvoice(
        ledger=repo,
        stripe=FakeInvoiceStripe(),
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert len(email.calls) == 1
    assert result.checkout_failure_code is None
    assert result.invoice.delivery_status == "sent"
    assert repo.payment_attempts == []


async def test_checkout_failure_without_email_port_leaves_delivery_untouched() -> None:
    """Parent-initiated 'Pay now' (email=None) must not corrupt the delivery
    axis of an invoice that was already emailed successfully."""
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(
                status="open",
                balance_due_cents=10_000,
                delivery_status="sent",
                sent_at=FIRST_SEND,
                last_sent_at=FIRST_SEND,
            )
        ]
    )
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe(),  # type: ignore[arg-type]
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert result.invoice.delivery_status == "sent"
    assert result.invoice.sent_at == FIRST_SEND
    assert result.checkout_failure_code == "checkout_creation_failed"


async def test_financial_status_unchanged_by_checkout_failure() -> None:
    """Key invariant holds on the new path too."""
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    result = await _blocked_uc(repo, email=FakeInvoiceEmail()).execute("inv-1")

    assert result.invoice.status == "open"
    assert result.invoice.balance_due_cents == 10_000


# ---------------------------------------------------------------------------
# #426 review follow-ups — the production shapes the first pass got wrong
# ---------------------------------------------------------------------------


async def test_academy_without_connect_account_still_emails_parent() -> None:
    """THE production case the first fix broke.

    compose_admin always passes the PLATFORM Stripe client, so `stripe=None`
    never happens in multi-tenant prod. An academy that simply never onboarded
    Connect has a live Stripe client but no connected-account row — it must
    still get its normal invoice email (with the contact-the-academy copy),
    and must NOT be recorded as a failure.
    """
    email = FakeInvoiceEmail()
    stripe = FakeInvoiceStripe()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    uc = SendInvoice(
        ledger=repo,
        stripe=stripe,  # platform client present, as in prod
        email=email,  # type: ignore[arg-type]
        connected_accounts=_FakeConnectedAccounts(None),  # never onboarded
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad-1", allow_platform_charge_fallback=False)
        ),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = await uc.execute("inv-1")

    assert stripe.calls == [], "must not mint a platform-charge link"
    assert len(email.calls) == 1, "parent must still receive the invoice"
    assert email.calls[0]["checkout_url"] is None
    assert result.invoice.delivery_status == "sent"
    assert result.checkout_failure_code is None
    assert repo.payment_attempts == [], "not onboarding Connect is not a failure"


async def test_connect_account_present_but_not_ready_is_still_a_failure() -> None:
    """Counterpart to the test above: an account that EXISTS but cannot charge
    means the academy wants online payments and is broken."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(invoices=[_invoice(status="open", balance_due_cents=10_000)])
    result = await _blocked_uc(repo, email=email).execute("inv-1")

    assert email.calls == []
    assert result.checkout_failure_code == "connected_account_not_ready"
    assert len(repo.payment_attempts) == 1


async def test_previously_sent_invoice_is_not_downgraded_on_resend_failure() -> None:
    """Admin re-send with a broken pay link must not erase the record that the
    parent already received an earlier email, nor stamp a fake last_sent_at."""
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(
        invoices=[
            _invoice(
                status="open",
                balance_due_cents=10_000,
                delivery_status="sent",
                sent_at=FIRST_SEND,
                last_sent_at=FIRST_SEND,
            )
        ]
    )
    result = await _blocked_uc(repo, email=email).execute("inv-1")

    assert email.calls == [], "still suppressed — no dead-end email"
    assert result.invoice.delivery_status == "sent", "March's delivery still happened"
    assert result.invoice.sent_at == FIRST_SEND
    assert result.invoice.last_sent_at == FIRST_SEND, "no send was attempted now"
    assert len(repo.payment_attempts) == 1, "but the failure is still recorded"


async def test_never_sent_invoice_is_marked_delivery_failed() -> None:
    email = FakeInvoiceEmail()
    repo = FakeLedgerRepository(
        invoices=[_invoice(status="open", balance_due_cents=10_000, delivery_status="not_sent")]
    )
    result = await _blocked_uc(repo, email=email).execute("inv-1")

    assert result.invoice.delivery_status == "delivery_failed"
    assert result.invoice.sent_at is None


async def test_bundled_failure_records_each_invoices_own_balance() -> None:
    """A bundled link over 3 x $100 is $300 of exposure, not 3 x $300."""
    invoices = [
        _invoice(invoice_id="inv-1", status="open", balance_due_cents=10_000),
        _invoice(invoice_id="inv-2", status="open", balance_due_cents=10_000),
        _invoice(invoice_id="inv-3", status="open", balance_due_cents=10_000),
    ]
    repo = FakeLedgerRepository(invoices=invoices)
    uc = SendInvoice(
        ledger=repo,
        stripe=_RaisingInvoiceStripe(),  # type: ignore[arg-type]
        email=None,
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    await uc.execute("inv-1", bundle_student_balance=True)

    assert len(repo.payment_attempts) == 3, "one row per invoice behind the link"
    assert {a["invoice_id"] for a in repo.payment_attempts} == {"inv-1", "inv-2", "inv-3"}
    assert [a["amount_cents"] for a in repo.payment_attempts] == [10_000, 10_000, 10_000]
    assert sum(a["amount_cents"] for a in repo.payment_attempts) == 30_000
