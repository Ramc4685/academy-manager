"""HandleWebhookEvent — Wave 2 fixture replay.

Asserts behavior for the canonical 10 Stripe scenarios (a representative
subset for unit-level coverage; full replay lives in the contract tests
which use real Stripe fixture JSON).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
        self.fail_next_save = False

    def seed(self, p: Payment) -> None:
        self.by_id[p.payment_id] = p
        if p.stripe_checkout_session_id:
            self.by_checkout[p.stripe_checkout_session_id] = p
        if p.stripe_payment_intent_id:
            self.by_pi[p.stripe_payment_intent_id] = p

    async def save(self, p: Payment) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("transient payment write failed")
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
        self.by_id: dict[str, Subscription] = {}
        self.by_stripe_sub: dict[str, Subscription] = {}
        self.by_enrollment: dict[str, Subscription] = {}

    def seed(self, subscription: Subscription) -> None:
        self.by_id[subscription.subscription_id] = subscription
        self.by_stripe_sub[subscription.stripe_subscription_id] = subscription
        if subscription.enrollment_id:
            self.by_enrollment[subscription.enrollment_id] = subscription

    async def save(self, _):
        self.seed(_)

    async def get(self, subscription_id):
        return self.by_id.get(subscription_id)

    async def get_by_stripe_sub(self, stripe_sub):
        return self.by_stripe_sub.get(stripe_sub)

    async def latest_for_enrollment(self, enrollment_id):
        return self.by_enrollment.get(enrollment_id)


class FakeDedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.processed: set[str] = set()
        self.events: dict[str, dict[str, Any]] = {}

    async def claim(self, event_id, _type):
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def mark_processed(self, event_id):
        self.processed.add(event_id)
        if event_id in self.events:
            self.events[event_id]["status"] = "processed"
            self.events[event_id]["processed_at"] = datetime.now(UTC)

    async def mark_failed(self, event_id, error):
        if event_id in self.events:
            self.events[event_id]["status"] = "failed"
            self.events[event_id]["error_message"] = error

    async def mark_quarantined(self, event_id, error):
        if event_id in self.events:
            self.events[event_id]["status"] = "quarantined"
            self.events[event_id]["error_message"] = error

    async def store_received(self, event, *, raw_payload, academy_id):
        event_id = str(event["id"])
        if event_id in self.events:
            return False
        obj = event.get("data", {}).get("object", {})
        metadata = obj.get("metadata") if isinstance(obj, dict) else None
        self.events[event_id] = {
            "event_id": event_id,
            "event_type": str(event["type"]),
            "academy_id": (metadata or {}).get("academy_id") or academy_id,
            "livemode": bool(event.get("livemode", False)),
            "status": "received",
            "retry_count": 0,
            "raw_payload": raw_payload,
            "received_at": datetime.now(UTC),
        }
        return True

    async def claim_next(self, *, academy_id, processor_id, lock_seconds=300):
        now = datetime.now(UTC)
        for event in self.events.values():
            if event.get("academy_id") != academy_id:
                continue
            retry_at = event.get("next_retry_at")
            if isinstance(retry_at, datetime) and retry_at > now:
                continue
            if event["status"] in {"received", "failed"}:
                event["status"] = "processing"
                event["processor_id"] = processor_id
                event["processing_started_at"] = now
                event["processing_locked_until"] = now + timedelta(seconds=lock_seconds)
                return dict(event)
        return None


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, _):
        pass


class FakeParentStripeCustomers:
    def __init__(self) -> None:
        self.saved: list[dict[str, str]] = []

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        self.saved.append({"parent_id": parent_id, "stripe_customer_id": stripe_customer_id})


class FakeEnrollmentAutopayState:
    def __init__(self) -> None:
        self.synced: list[dict[str, str | None]] = []

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        subscription_status: str,
        stripe_subscription_id: str | None,
    ) -> None:
        self.synced.append(
            {
                "enrollment_id": enrollment_id,
                "subscription_status": subscription_status,
                "stripe_subscription_id": stripe_subscription_id,
            }
        )


def _build(
    repo,
    outbox=None,
    dedup=None,
    subscriptions=None,
    parent_customers=None,
    enrollment_autopay=None,
    stripe=None,
    expected_livemode=None,
):
    return HandleWebhookEvent(
        stripe=stripe or FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=subscriptions or FakeSubscriptionRepo(),
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        outbox=outbox or FakeOutbox(),
        academy_id="acad",
        expected_livemode=expected_livemode,
    )


def _seed_pending_payment(repo: FakePaymentRepo) -> Payment:
    now = datetime.now(UTC)
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
async def test_accept_stores_webhook_event_without_business_side_effects() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_accept",
            "type": "checkout.session.completed",
            "livemode": True,
            "data": {
                "object": {
                    "id": "cs_1",
                    "payment_intent": "pi_1",
                    "metadata": {"academy_id": "acad"},
                }
            },
        }
    ).encode()

    res = await uc.accept(body, "test_signature")

    assert res == {"received": True, "stored": True, "type": "checkout.session.completed"}
    assert dedup.events["evt_async_accept"]["status"] == "received"
    assert repo.by_id["pay-1"].status == "pending"
    assert outbox.events == []


@pytest.mark.asyncio
async def test_process_next_projects_stored_event_and_marks_processed() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_process",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res == {
        "processed": True,
        "event_id": "evt_async_process",
        "type": "checkout.session.completed",
    }
    assert repo.by_id["pay-1"].status == "succeeded"
    assert repo.by_id["pay-1"].stripe_payment_intent_id == "pi_1"
    assert dedup.events["evt_async_process"]["status"] == "processed"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


@pytest.mark.asyncio
async def test_process_next_fetches_current_checkout_before_projection() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    subscriptions = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    subscriptions.seed(
        Subscription(
            subscription_id="app-sub-1",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="pending:cs_1",
            status="incomplete",
            created_at=now,
            updated_at=now,
        )
    )
    stripe = FakeStripeGateway()
    stripe.subscription_checkouts.append(
        {
            "checkout_id": "cs_1",
            "stripe_subscription_id": "sub_live_1",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "session_id": "s1",
            "amount_cents": 15000,
            "metadata": {
                "academy_id": "acad",
                "parent_id": "p1",
                "enrollment_id": "enr-1",
                "app_subscription_id": "app-sub-1",
            },
        }
    )
    parent_customers = FakeParentStripeCustomers()
    enrollment_autopay = FakeEnrollmentAutopayState()
    dedup = FakeDedup()
    uc = _build(
        repo,
        dedup=dedup,
        subscriptions=subscriptions,
        parent_customers=parent_customers,
        enrollment_autopay=enrollment_autopay,
        stripe=stripe,
    )
    body = json.dumps(
        {
            "id": "evt_hydrate_checkout",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert parent_customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_fake_parent"}]
    assert subscriptions.by_id["app-sub-1"].stripe_subscription_id == "sub_live_1"
    assert subscriptions.by_id["app-sub-1"].status == "active"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "active",
            "stripe_subscription_id": "sub_live_1",
        }
    ]


@pytest.mark.asyncio
async def test_failed_stored_event_can_be_retried_later() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    repo.fail_next_save = True
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_async_retry",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_intent": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    failed = await uc.process_next(processor_id="test-worker")
    retried = await uc.process_next(processor_id="test-worker")

    assert failed["processed"] is False
    assert failed["status"] == "failed"
    assert dedup.events["evt_async_retry"]["status"] == "processed"
    assert retried["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"


@pytest.mark.asyncio
async def test_wrong_livemode_event_is_quarantined() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup, expected_livemode=True)
    body = json.dumps(
        {
            "id": "evt_wrong_mode",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": "cs_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_wrong_mode"]["status"] == "quarantined"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_tenant_mismatch_event_is_quarantined() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()

    class MismatchedStripeGateway(FakeStripeGateway):
        async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
            return {
                "id": checkout_session_id,
                "object": "checkout.session",
                "status": "complete",
                "payment_status": "paid",
                "metadata": {"academy_id": "other-academy"},
            }

    uc = _build(repo, dedup=dedup, stripe=MismatchedStripeGateway())
    body = json.dumps(
        {
            "id": "evt_wrong_tenant",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "metadata": {"academy_id": "acad"},
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["status"] == "quarantined"
    assert dedup.events["evt_wrong_tenant"]["status"] == "quarantined"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_process_next_does_not_claim_other_academy_events() -> None:
    repo = FakePaymentRepo()
    _seed_pending_payment(repo)
    dedup = FakeDedup()
    uc = _build(repo, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_other_academy_pending",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "metadata": {"academy_id": "other-academy"},
                }
            },
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res == {"processed": False, "empty": True}
    assert dedup.events["evt_other_academy_pending"]["status"] == "received"
    assert repo.by_id["pay-1"].status == "pending"


@pytest.mark.asyncio
async def test_payment_intent_succeeded_marks_payment_succeeded() -> None:
    repo = FakePaymentRepo()
    payment = _seed_pending_payment(repo)
    repo.seed(payment.model_copy(update={"stripe_payment_intent_id": "pi_1"}))
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    body = json.dumps(
        {
            "id": "evt_pi_succeeded",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_1"}},
        }
    ).encode()

    await uc.accept(body, "test_signature")
    res = await uc.process_next(processor_id="test-worker")

    assert res["processed"] is True
    assert repo.by_id["pay-1"].status == "succeeded"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]


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
async def test_subscription_checkout_completed_saves_parent_stripe_customer() -> None:
    repo = FakePaymentRepo()
    customers = FakeParentStripeCustomers()
    uc = _build(repo, parent_customers=customers)
    body = json.dumps(
        {
            "id": "evt_subscription_checkout",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_subscription",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_parent",
                    "client_reference_id": "p1",
                    "metadata": {"parent_id": "p1", "subscription_id": "sub-1"},
                }
            },
        }
    ).encode()

    res = await uc.execute(body, "test_signature")

    assert res["received"] is True
    assert customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_live_parent"}]


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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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


def _seed_incomplete_subscription(
    subs: FakeSubscriptionRepo,
    *,
    stripe_subscription_id: str = "",
    status: str = "incomplete",
) -> Subscription:
    now = datetime.now(UTC)
    subscription = Subscription(
        subscription_id="sub-1",
        academy_id="acad",
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        stripe_subscription_id=stripe_subscription_id,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )
    subs.seed(subscription)
    return subscription


@pytest.mark.asyncio
async def test_subscription_checkout_completed_activates_subscription_and_enrollment() -> None:
    """Checkout completion must backfill the Stripe subscription id (null at
    checkout-creation time) and flip both the subscription row and the
    enrollment's autopay state to active — otherwise parents stay stuck at
    'incomplete' forever."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs)
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_checkout_done",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_sub_1",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_1",
                    "metadata": {
                        "parent_id": "p1",
                        "subscription_id": "sub-1",
                        "enrollment_id": "enr-1",
                    },
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    updated = subs.by_stripe_sub["sub_live_1"]
    assert updated.subscription_id == "sub-1"
    assert updated.status == "active"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "active",
            "stripe_subscription_id": "sub_live_1",
        }
    ]


@pytest.mark.asyncio
async def test_checkout_completed_binds_stripe_id_to_its_own_pending_subscription() -> None:
    """Two pending rows for one enrollment: completion must attach the Stripe
    id to the row named in the checkout's metadata.subscription_id, not to
    whichever row is newest for the enrollment."""
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    now = datetime.now(UTC)
    first = Subscription(
        subscription_id="sub-first",
        academy_id="acad",
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        stripe_subscription_id="",
        status="incomplete",
        created_at=now,
        updated_at=now,
    )
    newer = first.model_copy(update={"subscription_id": "sub-newer"})
    subs.seed(first)
    subs.seed(newer)  # latest_for_enrollment would return this one
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_checkout_first",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_first",
                    "customer": "cus_live_parent",
                    "subscription": "sub_live_first",
                    "metadata": {
                        "parent_id": "p1",
                        "subscription_id": "sub-first",
                        "enrollment_id": "enr-1",
                    },
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    bound = subs.by_stripe_sub["sub_live_first"]
    assert bound.subscription_id == "sub-first"
    assert bound.status == "active"
    # The unrelated newer pending row must remain untouched.
    assert subs.by_id["sub-newer"].stripe_subscription_id == ""
    assert subs.by_id["sub-newer"].status == "incomplete"


@pytest.mark.asyncio
async def test_subscription_updated_syncs_enrollment_autopay_state() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_updated",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_live_9", "status": "past_due"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert subs.by_stripe_sub["sub_live_9"].status == "past_due"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "past_due",
            "stripe_subscription_id": "sub_live_9",
        }
    ]


@pytest.mark.asyncio
async def test_subscription_deleted_syncs_enrollment_cancelled() -> None:
    repo = FakePaymentRepo()
    subs = FakeSubscriptionRepo()
    _seed_incomplete_subscription(subs, stripe_subscription_id="sub_live_9", status="active")
    enrollment_autopay = FakeEnrollmentAutopayState()
    uc = _build(repo, subscriptions=subs, enrollment_autopay=enrollment_autopay)
    body = json.dumps(
        {
            "id": "evt_sub_deleted",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_live_9", "status": "canceled"}},
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert subs.by_stripe_sub["sub_live_9"].status == "cancelled"
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "cancelled",
            "stripe_subscription_id": "sub_live_9",
        }
    ]


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
