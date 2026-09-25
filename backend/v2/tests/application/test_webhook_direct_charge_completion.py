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
    FakeDedup,
    FakeEnrollmentAutopayState,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
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
