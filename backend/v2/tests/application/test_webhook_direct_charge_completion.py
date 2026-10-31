"""A direct-charge autopay setup completes on the account the event names.

A non-house academy's setup checkout runs ON its connected account, so its
``checkout.session.completed`` arrives as a Connect event (top-level
``account``). The webhook must read the session, SetupIntent and payment
method back on that account (the account-aware fake answers
``resource_missing`` anywhere else) and record the saved card as living there.
A platform event (the house academy) keeps the historical, account-less calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.tests.application.test_webhook_handler import (
    FakeBillingLedger,
    FakeDedup,
    FakeEnrollmentAutopayState,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
    _ledger_invoice,
)

ACCT = "acct_direct_1"


class _Customers:
    """Records every write with its account kwarg (absent = platform)."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def set_stripe_customer_id(self, **kwargs: Any) -> None:
        self.writes.append(("customer", kwargs))

    async def set_default_payment_method(self, **kwargs: Any) -> None:
        self.writes.append(("default", kwargs))

    async def promote_payment_method_to_default(self, **kwargs: Any) -> None:
        self.writes.append(("promote", kwargs))


class _Accounts:
    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        return "acad" if stripe_account_id == ACCT else None

    async def get_by_stripe_account_id(self, stripe_account_id: str) -> ConnectedAccount | None:
        return None

    async def update_status(self, **_: Any) -> bool:  # pragma: no cover - unused
        return True


async def _complete(*, stripe_account: str | None) -> tuple[FakeStripeGateway, _Customers]:
    stripe = FakeStripeGateway()
    checkout_id, _ = await stripe.create_autopay_setup_checkout_session(
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        success_url="https://ok",
        cancel_url="https://cancel",
        metadata={
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
        **({"stripe_account": stripe_account} if stripe_account else {}),
    )
    customers = _Customers()
    uc = HandleWebhookEvent(
        stripe=stripe,
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        parent_customers=customers,  # type: ignore[arg-type]
        enrollment_autopay=FakeEnrollmentAutopayState(),
        connected_accounts=_Accounts(),  # type: ignore[arg-type]
        outbox=FakeOutbox(),
        academy_id="acad",
    )
    event: dict[str, Any] = {
        "id": f"evt_setup_{stripe_account or 'platform'}",
        "type": "checkout.session.completed",
        "data": {"object": {"id": checkout_id}},
    }
    if stripe_account:
        event["account"] = stripe_account
    await uc.accept(json.dumps(event).encode(), "test_signature")
    result = await uc.process_next(processor_id="test-worker")
    assert result["processed"] is True, result
    return stripe, customers


@pytest.mark.asyncio
async def test_connect_setup_completion_reads_and_records_on_the_account() -> None:
    stripe, customers = await _complete(stripe_account=ACCT)

    default = dict(next(kw for kind, kw in customers.writes if kind == "default"))
    promote = dict(next(kw for kind, kw in customers.writes if kind == "promote"))
    assert default["stripe_account_id"] == ACCT
    assert promote["stripe_account_id"] == ACCT
    assert stripe.account_of(default["stripe_customer_id"]) == ACCT
    assert stripe.account_of(default["stripe_payment_method_id"]) == ACCT
    assert stripe.customer_default_payment_methods[-1]["stripe_account"] == ACCT


@pytest.mark.asyncio
async def test_platform_setup_completion_is_unchanged() -> None:
    stripe, customers = await _complete(stripe_account=None)

    for _, kwargs in customers.writes:
        assert "stripe_account_id" not in kwargs
    assert "stripe_account" not in stripe.customer_default_payment_methods[-1]


# ---------------------------------------------------------------------------
# Failure paths that re-read Stripe objects must read them on the account too.
# ---------------------------------------------------------------------------

_INVOICE_METADATA = {
    "academy_id": "acad",
    "source": "invoice_pay_link",
    "invoice_id": "inv-direct",
    "parent_id": "parent-direct",
}


def _direct_invoice_checkout(stripe: FakeStripeGateway, *, checkout_id: str) -> None:
    """An invoice Checkout Session that exists ONLY on the connected account."""
    stripe.checkouts.append(
        {
            "checkout_id": checkout_id,
            "parent_id": "parent-direct",
            "session_id": "invoice-pay-link",
            "amount_cents": 10_000,
            "metadata": dict(_INVOICE_METADATA),
            "stripe_account": ACCT,
        }
    )
    stripe.register_object(checkout_id, stripe_account=ACCT)


def _ledger_handler(stripe: FakeStripeGateway, ledger: FakeBillingLedger) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=stripe,
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        billing_ledger=ledger,  # type: ignore[arg-type]
        connected_accounts=_Accounts(),  # type: ignore[arg-type]
        outbox=FakeOutbox(),
        academy_id="acad",
    )


@pytest.mark.asyncio
async def test_connect_invoice_checkout_pi_failure_reads_the_session_on_the_account() -> None:
    """payment_intent.payment_failed for a direct-charge invoice checkout: the
    handler looks the session up to find the invoice. On the platform that
    session does not exist (resource_missing), so the lookup must name the
    event's account or the failure is never recorded."""
    stripe = FakeStripeGateway()
    _direct_invoice_checkout(stripe, checkout_id="cs_direct_failed")
    stripe.register_object("pi_direct_failed", stripe_account=ACCT)
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-direct", parent_id="parent-direct"))
    uc = _ledger_handler(stripe, ledger)
    event = {
        "id": "evt_direct_pi_failed",
        "type": "payment_intent.payment_failed",
        "account": ACCT,
        "data": {
            "object": {
                "id": "pi_direct_failed",
                "amount": 10_000,
                "currency": "usd",
                "metadata": {},
                "payment_details": {"order_reference": "cs_direct_failed"},
                "last_payment_error": {"code": "card_declined", "message": "Declined."},
            }
        },
    }

    await uc.accept(json.dumps(event).encode(), "test_signature")
    result = await uc.process_next(processor_id="test-worker")

    assert result["processed"] is True, result
    [attempt] = ledger.payment_attempts.values()
    assert attempt["invoice_id"] == "inv-direct"
    assert attempt["status"] == "failed"
    assert attempt["failure_code"] == "card_declined"
    assert ledger.invoices["inv-direct"].status == "open"


@pytest.mark.asyncio
async def test_connect_async_payment_failure_reads_the_decline_on_the_account() -> None:
    """checkout.session.async_payment_failed for a direct-charge ACH checkout:
    the real decline reason is read off the PaymentIntent, which lives on the
    connected account. Read on the platform it is missing and the attempt
    would fall back to the generic placeholder."""
    stripe = FakeStripeGateway()
    _direct_invoice_checkout(stripe, checkout_id="cs_direct_ach")
    stripe.register_object("pi_direct_ach", stripe_account=ACCT)
    stripe._payment_intents_by_id["pi_direct_ach"] = {
        "id": "pi_direct_ach",
        "object": "payment_intent",
        "last_payment_error": {
            "code": "debit_not_authorized",
            "message": "The debit was not authorized.",
        },
    }
    ledger = FakeBillingLedger(_ledger_invoice(invoice_id="inv-direct", parent_id="parent-direct"))
    uc = _ledger_handler(stripe, ledger)
    event = {
        "id": "evt_direct_ach_failed",
        "type": "checkout.session.async_payment_failed",
        "account": ACCT,
        "data": {
            "object": {
                "id": "cs_direct_ach",
                "mode": "payment",
                "payment_status": "unpaid",
                "payment_intent": "pi_direct_ach",
                "amount_total": 10_000,
                "currency": "usd",
                "metadata": dict(_INVOICE_METADATA),
            }
        },
    }

    await uc.accept(json.dumps(event).encode(), "test_signature")
    result = await uc.process_next(processor_id="test-worker")

    assert result["processed"] is True, result
    failed = ledger.payment_attempts["invoice-checkout-failed:inv-direct:pi_direct_ach"]
    assert failed["failure_code"] == "debit_not_authorized"
    assert failed["failure_message"] == "The debit was not authorized."
