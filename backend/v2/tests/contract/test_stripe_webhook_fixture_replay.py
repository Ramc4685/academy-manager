"""Stripe webhook fixture replay.

Replays Stripe-shaped event JSON through `HandleWebhookEvent` and asserts
the resulting domain state. Fixtures live in `stripe_fixtures/` and are
hand-crafted to match the Stripe API shape; in production they should be
swapped for real captures from `stripe trigger <event-type>`.

Coverage:
- checkout.session.completed → Payment(status=succeeded) + outbox PaymentSucceeded
- checkout.session.completed replay (same event_id) → deduped
- checkout.session.expired → Payment(status=expired) + outbox CheckoutExpired
- payment_intent.payment_failed → Payment(status=failed) + outbox PaymentFailed
- charge.refunded partial → refunded_cents updated + status partially_refunded
- charge.refunded full → status refunded
- customer.subscription.updated → dispatch (no-op without seeded subscription)
- customer.subscription.deleted → dispatch (no-op)
- charge.dispute.created → ignored type, returns received without dispatching
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)

FIXTURES = Path(__file__).parent / "stripe_fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakePaymentRepo:
    def __init__(self):
        self.by_id: dict[str, Payment] = {}
        self.by_checkout: dict[str, Payment] = {}
        self.by_pi: dict[str, Payment] = {}

    def seed(self, p: Payment) -> None:
        self.by_id[p.payment_id] = p
        if p.stripe_checkout_session_id:
            self.by_checkout[p.stripe_checkout_session_id] = p
        if p.stripe_payment_intent_id:
            self.by_pi[p.stripe_payment_intent_id] = p

    async def save(self, p):
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
    async def save(self, _):
        pass

    async def get_by_stripe_sub(self, _):
        return None


class FakeDedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, event_id, _type):
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def mark_processed(self, _):
        pass

    async def mark_failed(self, _, __):
        pass


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, _limit=100):
        return []

    async def mark_processed(self, _):
        pass


def _build(repo, outbox=None, dedup=None):
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=FakeSubscriptionRepo(),
        outbox=outbox or FakeOutbox(),
        academy_id="test-academy",
    )


def _seed_pending(repo: FakePaymentRepo, *, payment_id: str, checkout_id: str | None = None, pi: str | None = None, status: str = "pending"):
    now = datetime.now(timezone.utc)
    p = Payment(
        payment_id=payment_id,
        academy_id="test-academy",
        parent_id=f"parent-{payment_id}",
        session_id=f"sess-{payment_id}",
        stripe_checkout_session_id=checkout_id,
        stripe_payment_intent_id=pi,
        amount_cents=15000,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )
    repo.seed(p)
    return p


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_checkout_completed_marks_succeeded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-001", checkout_id="cs_test_abcdef0000000001")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("checkout_session_completed.json"), "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-001"].status == "succeeded"
    assert repo.by_id["pay-001"].stripe_payment_intent_id == "pi_test_0000000001"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]
    succeeded = outbox.events[0]
    assert succeeded.payload.amount_cents == 15000
    assert succeeded.payload.session_id == "sess-pay-001"


@pytest.mark.asyncio
async def test_fixture_checkout_completed_dedupe_on_replay() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-001", checkout_id="cs_test_abcdef0000000001")
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    first = await uc.execute(_load("checkout_session_completed.json"), "test_signature")
    second = await uc.execute(_load("checkout_session_completed_duplicate.json"), "test_signature")
    assert first.get("type") == "checkout.session.completed"
    assert second.get("deduped") is True
    # Only one PaymentSucceeded emitted despite two webhook calls.
    assert sum(1 for e in outbox.events if e.name == "Billing.PaymentSucceeded") == 1


# ---------------------------------------------------------------------------
# checkout.session.expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_checkout_expired_transitions_pending_to_expired() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-002", checkout_id="cs_test_abcdef0000000002")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("checkout_session_expired.json"), "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-002"].status == "expired"
    assert outbox.events[0].name == "Billing.CheckoutExpired"


# ---------------------------------------------------------------------------
# payment_intent.payment_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_payment_failed_marks_failed_with_reason() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-003", pi="pi_test_0000000003")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("payment_intent_payment_failed.json"), "test_signature")
    assert repo.by_id["pay-003"].status == "failed"
    failed = outbox.events[0]
    assert failed.name == "Billing.PaymentFailed"
    assert "declined" in failed.payload.reason.lower()


# ---------------------------------------------------------------------------
# charge.refunded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_charge_refunded_partial_marks_partially_refunded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-004", pi="pi_test_0000000004", status="succeeded")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("charge_refunded_partial.json"), "test_signature")
    assert repo.by_id["pay-004"].refunded_cents == 5000
    assert repo.by_id["pay-004"].status == "partially_refunded"
    refunded = outbox.events[0]
    assert refunded.name == "Billing.PaymentRefunded"
    assert refunded.payload.total_refunded_cents == 5000


@pytest.mark.asyncio
async def test_fixture_charge_refunded_full_marks_refunded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-005", pi="pi_test_0000000005", status="succeeded")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("charge_refunded_full.json"), "test_signature")
    assert repo.by_id["pay-005"].refunded_cents == 15000
    assert repo.by_id["pay-005"].status == "refunded"


# ---------------------------------------------------------------------------
# customer.subscription.updated / deleted (no-op without seeded subscription)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_subscription_updated_skipped_when_unknown_subscription() -> None:
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    # Subscription repo is a fake that returns None — no state change, no event.
    res = await uc.execute(_load("customer_subscription_updated.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


@pytest.mark.asyncio
async def test_fixture_subscription_deleted_skipped_when_unknown_subscription() -> None:
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("customer_subscription_deleted.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


# ---------------------------------------------------------------------------
# Unknown / ignored event types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_charge_dispute_created_is_ignored() -> None:
    """Legacy didn't handle disputes; v2 currently ignores them too.
    If the product later needs dispute handling, this test will need
    updating + a new handler in HandleWebhookEvent._dispatch.
    """
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("charge_dispute_created.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


# ---------------------------------------------------------------------------
# Fixture sanity — make sure every JSON parses + has the required shape.
# ---------------------------------------------------------------------------


def test_all_fixtures_parse() -> None:
    for path in FIXTURES.glob("*.json"):
        body = json.loads(path.read_text())
        assert "id" in body
        assert "type" in body
        assert "data" in body
        assert "object" in body["data"]
