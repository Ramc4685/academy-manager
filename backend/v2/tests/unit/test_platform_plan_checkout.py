"""Growth tier use cases (Phase 2 A2): overview, checkout, and the webhook
projection onto ``TenantSubscription``."""

from __future__ import annotations

import asyncio
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
    CheckoutInProgress,
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
    def __init__(self, *, yield_on_read: bool = False) -> None:
        self.rows: dict[str, TenantSubscription] = {}
        self.saves = 0
        self.yield_on_read = yield_on_read

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        row = self.rows.get(academy_id)
        if self.yield_on_read:
            await asyncio.sleep(0)  # a concurrent request reads the same snapshot
        return row

    async def save(self, subscription: TenantSubscription) -> None:
        self.saves += 1
        self.rows[subscription.academy_id] = subscription

    async def claim_pending_checkout(
        self, subscription: TenantSubscription, *, expected_token: str | None, now: datetime
    ) -> bool:
        # Mirrors the Mongo CAS: only the pending fields are written on an
        # existing row, the whole row is inserted when there is none.
        current = self.rows.get(subscription.academy_id)
        if (current.pending_checkout_token if current else None) != expected_token:
            return False
        pending = {
            k: v for k, v in subscription.model_dump().items() if k.startswith("pending_checkout_")
        }
        self.rows[subscription.academy_id] = (
            current.model_copy(update={**pending, "updated_at": now}) if current else subscription
        )
        return True


class FakeStripe:
    def __init__(self) -> None:
        self.customers: list[dict[str, Any]] = []
        self.checkouts: list[dict[str, Any]] = []
        self.session_status: dict[str, str] = {}  # default "open"
        self.expired: list[str] = []
        self.cancelled: list[tuple[str, bool]] = []

    async def create_platform_customer(self, **kwargs: Any) -> str:
        self.customers.append(kwargs)
        return f"cus_{len(self.customers)}"

    async def create_platform_plan_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
        self.checkouts.append(kwargs)
        session_id = f"cs_{len(self.checkouts)}"
        return session_id, f"https://checkout.stripe.test/{session_id}"

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        return {
            "id": checkout_session_id,
            "status": self.session_status.get(checkout_session_id, "open"),
        }

    async def expire_checkout_session(self, checkout_session_id: str) -> None:
        if self.session_status.get(checkout_session_id) in ("complete", "expired"):
            raise ValueError("not expirable")
        self.expired.append(checkout_session_id)

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        self.cancelled.append((stripe_subscription_id, at_period_end))


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
        stripe_subscription_id="sub_growth_1",
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
        "checkout_token": row.pending_checkout_token,
    }
    assert row.pending_checkout_session_id == "cs_1"
    assert row.pending_checkout_url == url
    assert row.pending_checkout_created_at == NOW
    assert checkout["success_url"].endswith("plan=upgraded")
    event = audit.events[0]
    assert event.action == "tenant.plan_upgrade_started"
    assert event.actor_user_id == "u-owner"
    assert event.after_snapshot == {
        "from_plan_code": "none",
        "to_plan_code": "growth",
        "stripe_volume_90d_cents": 123_456,
    }

    # A second attempt continues the open session: no second payable one.
    assert await uc.execute(_command()) == url
    assert len(stripe.customers) == 1
    assert len(stripe.checkouts) == 1
    assert len(audit.events) == 1


def _seed_pending(
    subs: FakeSubscriptions,
    *,
    plan_id: str = "plan_growth",
    billing_status: str = "incomplete",
    stripe_subscription_id: str | None = None,
    created_at: datetime = NOW,
    session_id: str | None = "cs_old",
) -> TenantSubscription:
    row = TenantSubscription(
        subscription_id="platform_sub_seed",
        academy_id=ACADEMY,
        plan_id=plan_id,
        billing_status=billing_status,  # type: ignore[arg-type]
        stripe_customer_id="cus_1",
        stripe_subscription_id=stripe_subscription_id,
        pending_checkout_token="pco_old",
        pending_checkout_session_id=session_id,
        pending_checkout_url=f"https://checkout.stripe.test/{session_id}" if session_id else None,
        pending_checkout_created_at=created_at,
        created_at=NOW,
        updated_at=NOW,
    )
    subs.rows[ACADEMY] = row
    return row


@pytest.mark.asyncio
async def test_checkout_replaces_a_pending_session_older_than_stripe_keeps_it() -> None:
    plans, subs, stripe = FakePlans(_plan("growth")), FakeSubscriptions(), FakeStripe()
    _seed_pending(subs, created_at=NOW - timedelta(hours=24))
    url = await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert url == "https://checkout.stripe.test/cs_1"
    assert stripe.expired == ["cs_old"]  # best effort; Stripe already did
    row = subs.rows[ACADEMY]
    assert row.pending_checkout_session_id == "cs_1"
    assert row.pending_checkout_token != "pco_old"


@pytest.mark.asyncio
async def test_checkout_replaces_a_pending_session_stripe_reports_expired() -> None:
    plans, subs, stripe = FakePlans(_plan("growth")), FakeSubscriptions(), FakeStripe()
    _seed_pending(subs)
    stripe.session_status["cs_old"] = "expired"
    url = await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert url == "https://checkout.stripe.test/cs_1"
    assert stripe.expired == []  # refused by Stripe, swallowed
    assert subs.rows[ACADEMY].pending_checkout_session_id == "cs_1"


@pytest.mark.asyncio
async def test_checkout_waits_for_the_webhook_after_a_completed_session() -> None:
    # Paid on Stripe, not yet synced: a new session would open a second subscription.
    plans, subs, stripe = FakePlans(_plan("growth")), FakeSubscriptions(), FakeStripe()
    _seed_pending(subs)
    stripe.session_status["cs_old"] = "complete"
    with pytest.raises(CheckoutInProgress):
        await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert stripe.checkouts == []


@pytest.mark.asyncio
async def test_checkout_claim_in_flight_blocks_then_lapses() -> None:
    plans, subs, stripe = FakePlans(_plan("growth")), FakeSubscriptions(), FakeStripe()
    _seed_pending(subs, session_id=None, created_at=NOW - timedelta(minutes=9))
    with pytest.raises(CheckoutInProgress):
        await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert stripe.checkouts == []
    _seed_pending(subs, session_id=None, created_at=NOW - timedelta(minutes=10))
    url = await _checkout(plans, subs, stripe, _Audit()).execute(_command())
    assert url.endswith("cs_1")


@pytest.mark.asyncio
async def test_concurrent_checkouts_open_one_session() -> None:
    plans, stripe = FakePlans(_plan("growth")), FakeStripe()
    subs = FakeSubscriptions(yield_on_read=True)  # both read "no row" first
    uc = _checkout(plans, subs, stripe, _Audit())
    results = await asyncio.gather(
        uc.execute(_command()), uc.execute(_command()), return_exceptions=True
    )
    urls = [r for r in results if isinstance(r, str)]
    errors = [r for r in results if isinstance(r, CheckoutInProgress)]
    assert len(urls) == 1 and len(errors) == 1, results
    assert len(stripe.checkouts) == 1
    assert len(stripe.customers) == 1
    assert subs.rows[ACADEMY].pending_checkout_session_id == "cs_1"


@pytest.mark.asyncio
async def test_checkout_releases_the_claim_when_stripe_fails() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()

    class Boom(FakeStripe):
        async def create_platform_plan_checkout_session(self, **kwargs: Any) -> tuple[str, str]:
            raise RuntimeError("stripe down")

    with pytest.raises(RuntimeError):
        await _checkout(plans, subs, Boom(), _Audit()).execute(_command())
    assert subs.rows[ACADEMY].pending_checkout_token is None
    # The next request is not held for the claim grace window.
    stripe = FakeStripe()
    assert (await _checkout(plans, subs, stripe, _Audit()).execute(_command())).endswith("cs_1")


@pytest.mark.asyncio
async def test_checkout_allowed_on_a_lapsed_or_local_growth_trial() -> None:
    plans, stripe = FakePlans(_plan("growth")), FakeStripe()
    for trial_ends_at in (NOW - timedelta(days=1), NOW + timedelta(days=7)):
        subs = FakeSubscriptions()
        subs.rows[ACADEMY] = TenantSubscription(
            subscription_id="s1",
            academy_id=ACADEMY,
            plan_id="plan_growth",
            billing_status="trialing",
            trial_status="active",
            trial_ends_at=trial_ends_at,
            created_at=NOW,
            updated_at=NOW,
        )
        await _checkout(plans, subs, stripe, _Audit()).execute(_command())
        assert subs.rows[ACADEMY].pending_checkout_session_id
    # A Stripe-run trial is a live Growth subscription.
    subs = FakeSubscriptions()
    subs.rows[ACADEMY] = TenantSubscription(
        subscription_id="s1",
        academy_id=ACADEMY,
        plan_id="plan_growth",
        billing_status="trialing",
        stripe_subscription_id="sub_growth_1",
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(AlreadyOnGrowth):
        await _checkout(plans, subs, stripe, _Audit()).execute(_command())


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
                "created": 1793793600,
                "items": {
                    "object": "list",
                    "data": [{"id": "si_1", "price": {"id": "price_growth"}}],
                },
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


def _checkout_event(**extra: Any) -> dict[str, Any]:
    return {
        "id": "evt_cs",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_1",
                "created": 1793793600,
                "customer": "cus_1",
                "subscription": "sub_growth_1",
                "payment_status": "paid",
                "status": "complete",
                "metadata": {
                    "source": "platform_plan",
                    "academy_id": ACADEMY,
                    "plan_id": "plan_growth",
                },
                **extra,
            }
        },
    }


def _seed_incomplete(subs: FakeSubscriptions, *, plan_id: str = "plan_growth") -> None:
    # What StartGrowthCheckout writes before sending the owner to Stripe.
    subs.rows[ACADEMY] = TenantSubscription(
        subscription_id="platform_sub_seed",
        academy_id=ACADEMY,
        plan_id=plan_id,
        billing_status="incomplete",
        stripe_customer_id="cus_1",
        created_at=NOW,
        updated_at=NOW,
    )


def _sync(
    plans: FakePlans,
    subs: FakeSubscriptions,
    audit: _Audit | None = None,
    stripe: FakeStripe | None = None,
):
    return SyncTenantSubscriptionFromStripe(
        plans=plans,
        subscriptions=subs,
        stripe=stripe,
        stripe_volume=_volume,
        audit_recorder=audit,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_sync_creates_activates_and_unlocks_ai() -> None:
    plans, subs, audit = FakePlans(_plan("growth")), FakeSubscriptions(), _Audit()
    sync = _sync(plans, subs, audit)
    has_ai = HasFeature(plans=plans, subscriptions=subs, clock=lambda: NOW)
    _seed_incomplete(subs)
    assert await has_ai.execute(ACADEMY, "ai") is False

    await sync.execute("checkout.session.completed", _checkout_event())
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
                "price": {"id": "price_growth"},
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
async def test_sync_ignores_another_subscription_until_the_stored_one_is_cancelled() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    sync = _sync(plans, subs)
    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )
    # A second, even newer and active, subscription does not displace the live one...
    newer = _sub_event(
        "customer.subscription.created", "active", id="sub_growth_2", created=1793800000
    )
    await sync.execute("customer.subscription.created", newer)
    assert subs.rows[ACADEMY].stripe_subscription_id == "sub_growth_1"
    # ...nor does an older one's late delete touch it.
    await sync.execute(
        "customer.subscription.deleted",
        _sub_event(
            "customer.subscription.deleted", "canceled", id="sub_growth_0", created=1793700000
        ),
    )
    assert subs.rows[ACADEMY].billing_status == "active"
    # The current subscription's delete lands.
    await sync.execute(
        "customer.subscription.deleted",
        _sub_event("customer.subscription.deleted", "canceled", canceled_at=1796385600),
    )
    assert subs.rows[ACADEMY].billing_status == "cancelled"
    # Now cancelled: an OLDER subscription's event is still ignored...
    await sync.execute(
        "customer.subscription.updated",
        _sub_event(
            "customer.subscription.updated", "active", id="sub_growth_0", created=1793700000
        ),
    )
    assert subs.rows[ACADEMY].stripe_subscription_id == "sub_growth_1"
    # ...but the newer re-subscribe replaces it.
    await sync.execute("customer.subscription.created", newer)
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_2"
    assert row.billing_status == "active"
    assert row.stripe_subscription_created_at == datetime.fromtimestamp(1793800000, tz=UTC)


def _seed_flat_upgrading(subs: FakeSubscriptions) -> None:
    # Active Flat through ActivateTenantSubscription, then StartGrowthCheckout.
    _seed_pending(
        subs, plan_id="plan_flat", billing_status="active", stripe_subscription_id="sub_flat_1"
    )


def _flat_plans() -> FakePlans:
    return FakePlans(_plan("growth"), _plan("flat", price="price_flat", features=()))


@pytest.mark.asyncio
async def test_sync_flat_to_growth_cancels_the_old_subscription_checkout_first() -> None:
    plans, subs, audit, stripe = _flat_plans(), FakeSubscriptions(), _Audit(), FakeStripe()
    _seed_flat_upgrading(subs)
    sync = _sync(plans, subs, audit, stripe)
    await sync.execute("checkout.session.completed", _checkout_event(id="cs_old"))
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_1"
    assert row.plan_id == "plan_flat" and row.billing_status == "active"
    assert row.pending_checkout_token is None and row.pending_checkout_session_id is None
    assert stripe.cancelled == [("sub_flat_1", False)]

    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )
    row = subs.rows[ACADEMY]
    assert row.plan_id == "plan_growth" and row.billing_status == "active"
    assert stripe.cancelled == [("sub_flat_1", False)]  # once
    assert [e.action for e in audit.events] == ["tenant.plan_activated"]
    assert audit.events[0].after_snapshot["from_plan_code"] == "flat"
    # The old subscription's own delete is stale now.
    await sync.execute(
        "customer.subscription.deleted",
        _sub_event("customer.subscription.deleted", "canceled", id="sub_flat_1"),
    )
    assert subs.rows[ACADEMY].billing_status == "active"


@pytest.mark.asyncio
async def test_sync_flat_to_growth_accepts_the_subscription_event_first_by_token() -> None:
    plans, subs, stripe = _flat_plans(), FakeSubscriptions(), FakeStripe()
    _seed_flat_upgrading(subs)
    sync = _sync(plans, subs, stripe=stripe)
    event = _sub_event("customer.subscription.created", "active")
    event["data"]["object"]["metadata"]["checkout_token"] = "pco_old"
    await sync.execute("customer.subscription.created", event)
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_1" and row.plan_id == "plan_growth"
    assert row.pending_checkout_token is None
    assert stripe.cancelled == [("sub_flat_1", False)]
    # The late checkout event finds the ids already on file.
    await sync.execute("checkout.session.completed", _checkout_event(id="cs_old"))
    assert subs.rows[ACADEMY].stripe_subscription_id == "sub_growth_1"
    assert stripe.cancelled == [("sub_flat_1", False)]


@pytest.mark.asyncio
async def test_sync_keeps_flat_when_the_successor_is_not_entitled_or_unrelated() -> None:
    plans, subs, stripe = _flat_plans(), FakeSubscriptions(), FakeStripe()
    _seed_flat_upgrading(subs)
    sync = _sync(plans, subs, stripe=stripe)
    event = _sub_event("customer.subscription.created", "incomplete")
    event["data"]["object"]["metadata"]["checkout_token"] = "pco_old"
    await sync.execute("customer.subscription.created", event)
    # No token: the stale guard still holds for any other subscription.
    await sync.execute(
        "customer.subscription.created", _sub_event("customer.subscription.created", "active")
    )
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_flat_1" and row.plan_id == "plan_flat"
    assert row.pending_checkout_token == "pco_old"
    assert stripe.cancelled == []


@pytest.mark.asyncio
async def test_sync_clears_the_pending_checkout_on_a_fresh_academy() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    _seed_pending(subs)
    await _sync(plans, subs).execute("checkout.session.completed", _checkout_event(id="cs_old"))
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_1"
    assert row.pending_checkout_session_id is None and row.pending_checkout_token is None


@pytest.mark.asyncio
async def test_sync_resolves_the_plan_from_the_price_not_the_metadata() -> None:
    plans = FakePlans(_plan("growth"), _plan("flat", price="price_flat", features=()))
    subs = FakeSubscriptions()
    event = _sub_event("customer.subscription.created", "active")
    event["data"]["object"]["items"]["data"][0]["price"] = {"id": "price_flat"}
    await _sync(plans, subs).execute("customer.subscription.created", event)
    assert subs.rows[ACADEMY].plan_id == "plan_flat"  # metadata says plan_growth


@pytest.mark.asyncio
async def test_sync_ignores_an_unknown_price() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    for price in ({"id": "price_other"}, None):
        event = _sub_event("customer.subscription.created", "active")
        event["data"]["object"]["items"]["data"][0]["price"] = price
        await _sync(plans, subs).execute("customer.subscription.created", event)
    assert subs.rows == {}


@pytest.mark.asyncio
async def test_sync_ignores_events_for_another_customer() -> None:
    plans, subs = FakePlans(_plan("growth")), FakeSubscriptions()
    _seed_incomplete(subs)
    await _sync(plans, subs).execute(
        "customer.subscription.created",
        _sub_event("customer.subscription.created", "active", customer="cus_other"),
    )
    assert subs.rows[ACADEMY].billing_status == "incomplete"
    await _sync(plans, subs).execute(
        "checkout.session.completed", _checkout_event(customer="cus_other")
    )
    assert subs.rows[ACADEMY].stripe_subscription_id is None


@pytest.mark.asyncio
async def test_sync_checkout_records_ids_only_and_only_when_paid() -> None:
    plans = FakePlans(_plan("growth"), _plan("flat", price=None, features=()))
    subs = FakeSubscriptions()
    sync = _sync(plans, subs)
    # No row yet (nothing started the checkout): nothing to attach the ids to.
    await sync.execute("checkout.session.completed", _checkout_event())
    assert subs.rows == {}
    _seed_incomplete(subs, plan_id="plan_flat")
    await sync.execute(
        "checkout.session.completed", _checkout_event(payment_status="unpaid", status="open")
    )
    assert subs.rows[ACADEMY].stripe_subscription_id is None
    # Paid: ids recorded, but plan and status come only from the subscription event.
    await sync.execute("checkout.session.completed", _checkout_event(status="open"))
    row = subs.rows[ACADEMY]
    assert row.stripe_subscription_id == "sub_growth_1"
    assert row.plan_id == "plan_flat" and row.billing_status == "incomplete"


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
