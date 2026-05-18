"""HandleWebhookEvent — Wave 2 fixture replay.

Asserts behavior for the canonical 10 Stripe scenarios (a representative
subset for unit-level coverage; full replay lives in the contract tests
which use real Stripe fixture JSON).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.models import Payment, Subscription
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)


class FakePaymentRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, Payment] = {}
        self.by_checkout: dict[str, Payment] = {}
        self.by_pi: dict[str, Payment] = {}

    def seed(self, p: Payment) -> None:
        self.by_id[p.payment_id] = p
        if p.stripe_checkout_session_id:
            self.by_checkout[p.stripe_checkout_session_id] = p
        if p.stripe_payment_intent_id:
            self.by_pi[p.stripe_payment_intent_id] = p

    async def save(self, p: Payment) -> None:
        self.seed(p)

    async def get(self, pid):
        return self.by_id.get(pid)

    async def get_by_stripe_pi(self, pi):
        return self.by_pi.get(pi)

    async def get_by_checkout_session(self, sid):
        return self.by_checkout.get(sid)

    async def list_for_parent(self, _):
        return list(self.by_id.values())


class FakeSubscriptionRepo:
    def __init__(self) -> None:
        self.by_stripe_sub: dict[str, Subscription] = {}

    def seed(self, subscription: Subscription) -> None:
        self.by_stripe_sub[subscription.stripe_subscription_id] = subscription

    async def save(self, _):
        self.seed(_)

    async def get_by_stripe_sub(self, stripe_sub):
        return self.by_stripe_sub.get(stripe_sub)


class FakeDedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.processed: set[str] = set()

    async def claim(self, event_id, _type):
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def mark_processed(self, event_id):
        self.processed.add(event_id)

    async def mark_failed(self, event_id, error):
        pass


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, _):
        pass


def _build(repo, outbox=None, dedup=None, subscriptions=None):
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=subscriptions or FakeSubscriptionRepo(),
        outbox=outbox or FakeOutbox(),
        academy_id="acad",
    )


def _seed_pending_payment(repo: FakePaymentRepo) -> Payment:
    now = datetime.now(timezone.utc)
    p = Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="p1",
        session_id="s1",
        stripe_checkout_session_id="cs_1",
        amount_cents=15000,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    repo.seed(p)
    return p


@pytest.mark.asyncio
async def test_checkout_completed_marks_payment_succeeded_and_emits_event() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()
    res = await uc.execute(body, "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert repo.by_id["pay-1"].stripe_payment_intent_id == "pi_1"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


@pytest.mark.asyncio
async def test_dedup_short_circuits_replays() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_2",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    res = await uc.execute(body, "test_signature")
    assert res.get("deduped") is True


@pytest.mark.asyncio
async def test_checkout_expired_transitions_pending_to_expired() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_3",
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].status == "expired"
    assert [e.name for e in outbox.events] == ["Billing.CheckoutExpired"]


@pytest.mark.asyncio
async def test_payment_failed_marks_failed_and_emits() -> None:
    repo = FakePaymentRepo()
    p = _seed_pending_payment(repo)
    repo.seed(p.model_copy(update={"stripe_payment_intent_id": "pi_x"}))
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_4",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_x", "last_payment_error": {"message": "card declined"}}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].status == "failed"
    assert outbox.events[0].name == "Billing.PaymentFailed"


@pytest.mark.asyncio
async def test_invoice_paid_creates_subscription_payment_and_emits() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(timezone.utc)
    subs.seed(
        Subscription(
            subscription_id="sub-1",
            academy_id="acad",
            parent_id="p1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-1",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, subscriptions=subs)
    body = json.dumps(
        {
            "id": "evt_invoice_1",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_1",
                    "subscription": "stripe-sub-1",
                    "payment_intent": "pi_invoice_1",
                    "amount_paid": 16000,
                    "currency": "usd",
                }
            },
        }
    ).encode()
    await uc.execute(body, "test_signature")
    payment = repo.by_pi["pi_invoice_1"]
    assert payment.status == "succeeded"
    assert payment.subscription_id == "sub-1"
    assert payment.session_id == "s1"
    assert outbox.events[0].name == "Billing.PaymentSucceeded"


@pytest.mark.asyncio
async def test_invoice_payment_failed_creates_failed_subscription_payment() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(timezone.utc)
    subs.seed(
        Subscription(
            subscription_id="sub-2",
            academy_id="acad",
            parent_id="p1",
            session_id="s1",
            stripe_subscription_id="stripe-sub-2",
            status="past_due",
            created_at=now,
            updated_at=now,
        )
    )
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox, subscriptions=subs)
    body = json.dumps(
        {
            "id": "evt_invoice_2",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_2",
                    "subscription": "stripe-sub-2",
                    "payment_intent": "pi_invoice_2",
                    "amount_due": 16000,
                    "currency": "usd",
                    "last_finalization_error": {"message": "card declined"},
                }
            },
        }
    ).encode()
    await uc.execute(body, "test_signature")
    payment = repo.by_pi["pi_invoice_2"]
    assert payment.status == "failed"
    assert payment.subscription_id == "sub-2"
    assert outbox.events[0].name == "Billing.PaymentFailed"


@pytest.mark.asyncio
async def test_charge_refunded_updates_cumulative_amount() -> None:
    repo = FakePaymentRepo()
    p = _seed_pending_payment(repo)
    repo.seed(p.model_copy(update={"stripe_payment_intent_id": "pi_y", "status": "succeeded"}))
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    body = json.dumps(
        {
            "id": "evt_5",
            "type": "charge.refunded",
            "data": {"object": {"payment_intent": "pi_y", "amount_refunded": 5000}},
        }
    ).encode()
    await uc.execute(body, "test_signature")
    assert repo.by_id["pay-1"].refunded_cents == 5000
    assert repo.by_id["pay-1"].status == "partially_refunded"


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored() -> None:
    repo = FakePaymentRepo()
    uc = _build(repo)
    body = json.dumps(
        {
            "id": "evt_6",
            "type": "customer.created",
            "data": {"object": {}},
        }
    ).encode()
    res = await uc.execute(body, "test_signature")
    assert res["received"] is True
