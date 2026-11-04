"""Growth tier use cases (Phase 2 A2): overview, checkout, and the webhook
projection onto ``TenantSubscription``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    HasFeature,
)
from backend.v2.contexts.platform.billing.application.use_cases.plan_checkout import (
    AlreadyOnGrowth,
    GetPlanOverview,
    GrowthPlanUnavailable,
    StartGrowthCheckout,
    StartGrowthCheckoutCommand,
    SyncTenantSubscriptionFromStripe,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlatformPlan,
    TenantSubscription,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
ACADEMY = "acad-1"


class FakePlans:
    def __init__(self, *plans: PlatformPlan) -> None:
        self.rows = {p.plan_id: p for p in plans}

    async def get(self, plan_id: str) -> PlatformPlan | None:
        return self.rows.get(plan_id)

    async def list(self) -> list[PlatformPlan]:
        return list(self.rows.values())

    async def save(self, plan: PlatformPlan) -> None:
        self.rows[plan.plan_id] = plan


class FakeSubscriptions:
    def __init__(self) -> None:
        self.rows: dict[str, TenantSubscription] = {}
        self.saves = 0

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        return self.rows.get(academy_id)

    async def save(self, subscription: TenantSubscription) -> None:
        self.saves += 1
        self.rows[subscription.academy_id] = subscription


class FakeStripe:
    def __init__(self) -> None:
        self.customers: list[dict[str, Any]] = []
        self.checkouts: list[dict[str, Any]] = []

    async def create_platform_customer(self, **kwargs: Any) -> str:
        self.customers.append(kwargs)
        return f"cus_{len(self.customers)}"

    async def create_platform_plan_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
        self.checkouts.append(kwargs)
        return "cs_1", "https://checkout.stripe.test/cs_1"


def _plan(code: str, *, price: str | None = "price_growth", features=("ai",)) -> PlatformPlan:
    return PlatformPlan(
        plan_id=f"plan_{code}",
        code=code,
        display_name=code.title(),
        monthly_price_cents=9900,
        limits=PlanLimits(),
        stripe_price_id=price,
        features=frozenset(features),
        created_at=NOW,
        updated_at=NOW,
    )


class _Audit:
    def __init__(self) -> None:
        self.events: list[RecordPlatformAuditEventCommand] = []

    async def __call__(self, command: RecordPlatformAuditEventCommand) -> None:
        self.events.append(command)


async def _volume(since: datetime) -> int:
    assert since == NOW - timedelta(days=90)
    return 123_456


def _checkout(plans: FakePlans, subs: FakeSubscriptions, stripe: FakeStripe, audit: _Audit):
    return StartGrowthCheckout(
        plans=plans,
        subscriptions=subs,
        stripe=stripe,
        stripe_volume=_volume,
        audit_recorder=audit,
        clock=lambda: NOW,
    )


def _command() -> StartGrowthCheckoutCommand:
    return StartGrowthCheckoutCommand(
        academy_id=ACADEMY,
        academy_name="BLNO",
        actor_user_id="u-owner",
        actor_email="owner@blno.test",
        success_url="https://blno.test/admin/settings?panel=integrations&plan=upgraded",
        cancel_url="https://blno.test/admin/settings?panel=integrations&plan=cancelled",
    )


# --- overview ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_without_a_subscription_offers_growth_when_priced() -> None:
    plans = FakePlans(_plan("growth"))
    out = await GetPlanOverview(plans=plans, subscriptions=FakeSubscriptions()).execute(ACADEMY)
    assert out.subscription is None and out.plan is None
    assert out.growth is not None and out.growth.code == "growth"
    assert out.checkout_available is True


@pytest.mark.asyncio
async def test_overview_checkout_unavailable_without_a_price_id() -> None:
    plans = FakePlans(_plan("growth", price=None))
    out = await GetPlanOverview(plans=plans, subscriptions=FakeSubscriptions()).execute(ACADEMY)
    assert out.checkout_available is False


# --- checkout ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_refuses_without_a_price_id() -> None:
    with pytest.raises(GrowthPlanUnavailable):
        await _checkout(
            FakePlans(_plan("growth", price=None)), FakeSubscriptions(), FakeStripe(), _Audit()
        ).execute(_command())


@pytest.mark.asyncio
async def test_checkout_refuses_when_already_on_growth() -> None:
    subs = FakeSubscriptions()
    subs.rows[ACADEMY] = TenantSubscription(
        subscription_id="s1",
        academy_id=ACADEMY,
        plan_id="plan_growth",
        billing_status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(AlreadyOnGrowth):
        await _checkout(FakePlans(_plan("growth")), subs, FakeStripe(), _Audit()).execute(
            _command()
        )


@pytest.mark.asyncio
async def test_checkout_refuses_while_the_growth_subscription_is_past_due() -> None:
    plans, subs, stripe = FakePlans(_plan("growth")), FakeSubscriptions(), FakeStripe()
    subs.rows[ACADEMY] = TenantSubscription(
        subscription_id="platform_sub_1",
        academy_id=ACADEMY,
        plan_id="plan_growth",
        billing_status="past_due",
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_growth_1",
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(AlreadyOnGrowth):
        await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert stripe.checkouts == []


@pytest.mark.asyncio
async def test_checkout_creates_the_customer_once_and_audits_the_volume() -> None:
    plans, subs, stripe, audit = (
        FakePlans(_plan("growth")),
        FakeSubscriptions(),
        FakeStripe(),
        _Audit(),
    )
    uc = _checkout(plans, subs, stripe, audit)

    url = await uc.execute(_command())
    assert url == "https://checkout.stripe.test/cs_1"
    row = subs.rows[ACADEMY]
    assert row.billing_status == "incomplete"
    assert row.stripe_customer_id == "cus_1"
    assert stripe.customers == [
        {"name": "BLNO", "email": "owner@blno.test", "metadata": {"academy_id": ACADEMY}}
    ]
    checkout = stripe.checkouts[0]
    assert checkout["customer_id"] == "cus_1"
    assert checkout["price_id"] == "price_growth"
    assert checkout["metadata"] == {
        "source": "platform_plan",
        "academy_id": ACADEMY,
        "plan_id": "plan_growth",
    }
    assert checkout["success_url"].endswith("plan=upgraded")
    event = audit.events[0]
    assert event.action == "tenant.plan_upgrade_started"
    assert event.actor_user_id == "u-owner"
    assert event.after_snapshot == {
        "from_plan_code": "none",
        "to_plan_code": "growth",
        "stripe_volume_90d_cents": 123_456,
    }

    # A second attempt (abandoned checkout) reuses the customer.
    await uc.execute(_command())
    assert len(stripe.customers) == 1
    assert stripe.checkouts[1]["customer_id"] == "cus_1"


@pytest.mark.asyncio
async def test_checkout_from_a_flat_plan_records_the_from_code() -> None:
    plans = FakePlans(_plan("growth"), _plan("flat", price=None, features=()))
    subs, stripe, audit = FakeSubscriptions(), FakeStripe(), _Audit()
    subs.rows[ACADEMY] = TenantSubscription(
        subscription_id="s1",
        academy_id=ACADEMY,
        plan_id="plan_flat",
        billing_status="active",
        stripe_customer_id="cus_existing",
        created_at=NOW,
        updated_at=NOW,
    )
    await _checkout(plans, subs, stripe, audit).execute(_command())
    assert stripe.customers == []
    assert audit.events[0].after_snapshot["from_plan_code"] == "flat"
    # The row keeps its plan until Stripe confirms the new subscription.
    assert subs.rows[ACADEMY].plan_id == "plan_flat"


# --- webhook sync -----------------------------------------------------------


def _sub_event(event_type: str, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"evt_{event_type}_{status}",
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_growth_1",
                "object": "subscription",
                "customer": "cus_1",
                "status": status,
                "current_period_start": 1793793600,
                "current_period_end": 1796385600,
                "cancel_at_period_end": False,
                "metadata": {
                    "source": "platform_plan",
                    "academy_id": ACADEMY,
                    "plan_id": "plan_growth",
                },
                **extra,
            }
        },
    }


def _sync(plans: FakePlans, subs: FakeSubscriptions, audit: _Audit | None = None):
    return SyncTenantSubscriptionFromStripe(
        plans=plans,
        subscriptions=subs,
        stripe_volume=_volume,
        audit_recorder=audit,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_sync_creates_activates_and_unlocks_ai() -> None:
    plans, subs, audit = FakePlans(_plan("growth")), FakeSubscriptions(), _Audit()
    sync = _sync(plans, subs, audit)
    has_ai = HasFeature(plans=plans, subscriptions=subs, clock=lambda: NOW)
    assert await has_ai.execute(ACADEMY, "ai") is False

    session = {
        "id": "evt_cs",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_1",
                "customer": "cus_1",
                "subscription": "sub_growth_1",
                "metadata": {
                    "source": "platform_plan",
                    "academy_id": ACADEMY,
                    "plan_id": "plan_growth",
                },
            }
        },
    }
    await sync.execute("checkout.session.completed", session)
    row = subs.rows[ACADEMY]
    assert row.billing_status == "incomplete"
    assert row.stripe_subscription_id == "sub_growth_1"
    assert row.stripe_customer_id == "cus_1"
    assert audit.events == []

    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )
    row = subs.rows[ACADEMY]
    assert row.billing_status == "active"
    assert row.plan_id == "plan_growth"
    assert row.current_period_start == datetime.fromtimestamp(1793793600, tz=UTC)
    assert row.current_period_end == datetime.fromtimestamp(1796385600, tz=UTC)
    assert await has_ai.execute(ACADEMY, "ai") is True
    assert [e.action for e in audit.events] == ["tenant.plan_activated"]
    activated = audit.events[0]
    assert activated.actor_user_id == "stripe_webhook"
    assert activated.after_snapshot == {
        "from_plan_code": "none",
        "to_plan_code": "growth",
        "stripe_subscription_id": "sub_growth_1",
        "stripe_volume_90d_cents": 123_456,
    }


@pytest.mark.asyncio
async def test_sync_replay_converges_and_does_not_audit_twice() -> None:
    plans, subs, audit = FakePlans(_plan("growth")), FakeSubscriptions(), _Audit()
    sync = _sync(plans, subs, audit)
    event = _sub_event("customer.subscription.updated", "active")
    await sync.execute("customer.subscription.updated", event)
    first = subs.rows[ACADEMY]
    await sync.execute("customer.subscription.updated", event)
    assert subs.rows[ACADEMY] == first
    assert len(audit.events) == 1


@pytest.mark.asyncio
async def test_sync_maps_cancel_at_period_end_and_deleted() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    sync = _sync(plans, subs)
    has_ai = HasFeature(plans=plans, subscriptions=subs, clock=lambda: NOW)
    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )

    await sync.execute(
        "customer.subscription.updated",
        _sub_event("customer.subscription.updated", "active", cancel_at_period_end=True),
    )
    row = subs.rows[ACADEMY]
    assert row.cancel_at_period_end is True
    assert row.cancellation_status == "scheduled"
    assert await has_ai.execute(ACADEMY, "ai") is True  # until the period ends

    await sync.execute(
        "customer.subscription.deleted",
        _sub_event("customer.subscription.deleted", "canceled", canceled_at=1796385600),
    )
    row = subs.rows[ACADEMY]
    assert row.billing_status == "cancelled"
    assert row.cancellation_status == "cancelled"
    assert row.cancelled_at == datetime.fromtimestamp(1796385600, tz=UTC)
    assert await has_ai.execute(ACADEMY, "ai") is False


@pytest.mark.asyncio
async def test_sync_reads_the_period_from_the_items_on_dahlia_subscriptions() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    event = _sub_event("customer.subscription.updated", "active", cancel_at_period_end=True)
    obj = event["data"]["object"]
    del obj["current_period_start"], obj["current_period_end"]
    obj["items"] = {
        "object": "list",
        "data": [
            {
                "id": "si_1",
                "current_period_start": 1793793600,
                "current_period_end": 1796385600,
            }
        ],
    }
    await _sync(plans, subs).execute("customer.subscription.updated", event)
    row = subs.rows[ACADEMY]
    assert row.current_period_start == datetime.fromtimestamp(1793793600, tz=UTC)
    assert row.current_period_end == datetime.fromtimestamp(1796385600, tz=UTC)
    after_period = datetime.fromtimestamp(1796385600, tz=UTC) + timedelta(seconds=1)
    has_ai = HasFeature(plans=plans, subscriptions=subs, clock=lambda: after_period)
    assert await has_ai.execute(ACADEMY, "ai") is False


@pytest.mark.asyncio
async def test_sync_ignores_a_late_cancel_for_an_older_subscription() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    sync = _sync(plans, subs)
    has_ai = HasFeature(plans=plans, subscriptions=subs, clock=lambda: NOW)
    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )
    # Re-subscribed: the new subscription goes active first...
    new_sub = _sub_event("customer.subscription.created", "active", id="sub_growth_2")
    await sync.execute("customer.subscription.created", new_sub)
    assert subs.rows[ACADEMY].stripe_subscription_id == "sub_growth_2"
    # ...then the old subscription's delete arrives late.
    await sync.execute(
        "customer.subscription.deleted",
        _sub_event("customer.subscription.deleted", "canceled", canceled_at=1796385600),
    )
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_2"
    assert row.billing_status == "active"
    assert await has_ai.execute(ACADEMY, "ai") is True
    # A delete for the current subscription still lands.
    await sync.execute(
        "customer.subscription.deleted",
        _sub_event("customer.subscription.deleted", "canceled", id="sub_growth_2"),
    )
    assert subs.rows[ACADEMY].billing_status == "cancelled"


@pytest.mark.asyncio
async def test_sync_maps_past_due_and_unpaid_off_entitlement() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    sync = _sync(plans, subs)
    for stripe_status, expected in (
        ("past_due", "past_due"),
        ("unpaid", "unpaid"),
        ("trialing", "trialing"),
    ):
        await sync.execute(
            "customer.subscription.updated",
            _sub_event("customer.subscription.updated", stripe_status),
        )
        assert subs.rows[ACADEMY].billing_status == expected


@pytest.mark.asyncio
async def test_sync_ignores_an_event_without_academy_metadata() -> None:
    subs = FakeSubscriptions()
    event = _sub_event("customer.subscription.updated", "active")
    event["data"]["object"]["metadata"] = {"source": "platform_plan"}
    await _sync(FakePlans(_plan("growth")), subs).execute("customer.subscription.updated", event)
    assert subs.rows == {}
