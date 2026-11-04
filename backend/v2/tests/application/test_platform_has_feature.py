"""``has_feature``: PlatformPlan + TenantSubscription is the entitlement truth."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    HasFeature,
    UpsertPlatformPlan,
    UpsertPlatformPlanCommand,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlatformPlan,
    TenantSubscription,
)
from backend.v2.contexts.platform.billing.infrastructure.mongo_repositories import (
    MongoPlatformPlanRepository,
    MongoTenantSubscriptionRepository,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)


class FakePlans:
    def __init__(self, *plans: PlatformPlan) -> None:
        self._plans = {p.plan_id: p for p in plans}

    async def get(self, plan_id: str) -> PlatformPlan | None:
        return self._plans.get(plan_id)


class FakeSubscriptions:
    def __init__(self, *subs: TenantSubscription) -> None:
        self._subs = {s.academy_id: s for s in subs}

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        return self._subs.get(academy_id)


def _plan(status: str = "active", features: frozenset[str] = frozenset({"ai"})) -> PlatformPlan:
    return PlatformPlan(
        plan_id="plan-growth",
        code="growth",
        display_name="Growth",
        monthly_price_cents=9_900,
        limits=PlanLimits(),
        status=status,
        features=features,
        created_at=NOW,
        updated_at=NOW,
    )


def _sub(academy_id: str, billing_status: str = "active") -> TenantSubscription:
    return TenantSubscription(
        subscription_id=f"sub-{academy_id}",
        academy_id=academy_id,
        plan_id="plan-growth",
        billing_status=billing_status,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_no_subscription_is_false() -> None:
    use_case = HasFeature(plans=FakePlans(_plan()), subscriptions=FakeSubscriptions())
    assert await use_case.execute("acad-1", "ai") is False


@pytest.mark.parametrize("status", ["active", "trialing"])
async def test_entitled_subscription_on_a_plan_with_the_feature_is_true(status: str) -> None:
    use_case = HasFeature(
        plans=FakePlans(_plan()), subscriptions=FakeSubscriptions(_sub("acad-1", status))
    )
    assert await use_case.execute("acad-1", "ai") is True
    assert await use_case.execute("acad-1", "video") is False


@pytest.mark.parametrize("status", ["past_due", "unpaid", "incomplete", "cancelled"])
async def test_subscription_outside_entitled_statuses_is_false(status: str) -> None:
    use_case = HasFeature(
        plans=FakePlans(_plan()), subscriptions=FakeSubscriptions(_sub("acad-1", status))
    )
    assert await use_case.execute("acad-1", "ai") is False


async def test_archived_or_missing_plan_is_false() -> None:
    subs = FakeSubscriptions(_sub("acad-1"))
    assert (
        await HasFeature(plans=FakePlans(_plan("archived")), subscriptions=subs).execute(
            "acad-1", "ai"
        )
        is False
    )
    assert await HasFeature(plans=FakePlans(), subscriptions=subs).execute("acad-1", "ai") is False


async def test_plan_features_default_empty() -> None:
    assert _plan(features=frozenset()).features == frozenset()
    assert PlatformPlan.model_validate(
        {**_plan().model_dump(), "features": ["ai", "ai"]}
    ).features == frozenset({"ai"})


async def test_features_round_trip_through_mongo_and_upsert() -> None:
    db = AsyncMongoMockClient()["test_db"]
    plans = MongoPlatformPlanRepository(db)
    await UpsertPlatformPlan(plans=plans, clock=lambda: NOW).execute(
        UpsertPlatformPlanCommand(
            plan_id="plan-growth",
            code="growth",
            display_name="Growth",
            monthly_price_cents=9_900,
            limits=PlanLimits(),
            features=frozenset({"ai"}),
        )
    )
    stored = await db["platform_plans"].find_one({"plan_id": "plan-growth"})
    assert stored["features"] == ["ai"]
    assert (await plans.get("plan-growth")).features == frozenset({"ai"})

    subs = MongoTenantSubscriptionRepository(db)
    await subs.save(_sub("acad-1"))
    assert await HasFeature(plans=plans, subscriptions=subs).execute("acad-1", "ai") is True
