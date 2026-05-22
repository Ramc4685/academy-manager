from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ActivateTenantSubscription,
    ActivateTenantSubscriptionCommand,
    CheckPlanLimits,
    PlatformUsage,
    ScheduleTenantCancellation,
    ScheduleTenantCancellationCommand,
    StartTenantTrial,
    StartTenantTrialCommand,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlatformPlan,
    TenantSubscription,
)


class FakePlanRepository:
    def __init__(self, plans: list[PlatformPlan]) -> None:
        self._plans = {plan.plan_id: plan for plan in plans}

    async def get(self, plan_id: str) -> PlatformPlan | None:
        return self._plans.get(plan_id)


class FakeTenantSubscriptionRepository:
    def __init__(self) -> None:
        self.saved: list[TenantSubscription] = []
        self.by_academy: dict[str, TenantSubscription] = {}

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        return self.by_academy.get(academy_id)

    async def save(self, subscription: TenantSubscription) -> None:
        self.saved.append(subscription)
        self.by_academy[subscription.academy_id] = subscription


def _clock() -> datetime:
    return datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _plan() -> PlatformPlan:
    return PlatformPlan(
        plan_id="plan-growth",
        code="growth",
        display_name="Growth",
        monthly_price_cents=29_900,
        currency="usd",
        limits=PlanLimits(
            max_active_students=250,
            max_locations=2,
            max_staff_members=12,
        ),
        status="active",
        created_at=_clock(),
        updated_at=_clock(),
    )


@pytest.mark.asyncio
async def test_start_trial_creates_platform_subscription_without_tuition_fields() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    trial_ends_at = _clock() + timedelta(days=14)

    result = await StartTenantTrial(
        plans=plans,
        subscriptions=subscriptions,
        id_factory=lambda: "platform-sub-1",
        clock=_clock,
    ).execute(
        StartTenantTrialCommand(
            academy_id="academy-1",
            plan_id="plan-growth",
            trial_ends_at=trial_ends_at,
        )
    )

    assert result.academy_id == "academy-1"
    assert result.plan_id == "plan-growth"
    assert result.billing_status == "trialing"
    assert result.trial_status == "active"
    assert result.cancellation_status == "none"
    assert result.stripe_customer_id is None
    assert result.stripe_subscription_id is None
    assert result.trial_ends_at == trial_ends_at

    tuition_fields = {"parent_id", "student_id", "enrollment_id", "session_id"}
    assert tuition_fields.isdisjoint(TenantSubscription.model_fields)


@pytest.mark.asyncio
async def test_activate_stripe_subscription_records_customer_subscription_and_plan() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    await subscriptions.save(
        TenantSubscription(
            subscription_id="platform-sub-1",
            academy_id="academy-1",
            plan_id="plan-growth",
            billing_status="trialing",
            trial_status="active",
            cancellation_status="none",
            trial_ends_at=_clock() + timedelta(days=14),
            created_at=_clock(),
            updated_at=_clock(),
        )
    )

    result = await ActivateTenantSubscription(
        plans=plans,
        subscriptions=subscriptions,
        id_factory=lambda: "platform-sub-unused",
        clock=_clock,
    ).execute(
        ActivateTenantSubscriptionCommand(
            academy_id="academy-1",
            plan_id="plan-growth",
            stripe_customer_id="cus_platform_123",
            stripe_subscription_id="sub_platform_123",
            current_period_start=_clock(),
            current_period_end=_clock() + timedelta(days=30),
        )
    )

    assert result.subscription_id == "platform-sub-1"
    assert result.billing_status == "active"
    assert result.trial_status == "converted"
    assert result.cancellation_status == "none"
    assert result.stripe_customer_id == "cus_platform_123"
    assert result.stripe_subscription_id == "sub_platform_123"
    assert result.current_period_end == _clock() + timedelta(days=30)


@pytest.mark.asyncio
async def test_schedule_cancellation_keeps_subscription_active_until_period_end() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    await subscriptions.save(
        TenantSubscription(
            subscription_id="platform-sub-1",
            academy_id="academy-1",
            plan_id="plan-growth",
            billing_status="active",
            trial_status="converted",
            cancellation_status="none",
            stripe_customer_id="cus_platform_123",
            stripe_subscription_id="sub_platform_123",
            current_period_start=_clock(),
            current_period_end=_clock() + timedelta(days=30),
            created_at=_clock(),
            updated_at=_clock(),
        )
    )

    result = await ScheduleTenantCancellation(
        plans=plans,
        subscriptions=subscriptions,
        clock=_clock,
    ).execute(
        ScheduleTenantCancellationCommand(
            academy_id="academy-1",
            cancel_at_period_end=True,
        )
    )

    assert result.billing_status == "active"
    assert result.cancellation_status == "scheduled"
    assert result.cancel_at_period_end is True
    assert result.cancelled_at is None


@pytest.mark.asyncio
async def test_check_plan_limits_reports_exceeded_tenant_usage() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    await subscriptions.save(
        TenantSubscription(
            subscription_id="platform-sub-1",
            academy_id="academy-1",
            plan_id="plan-growth",
            billing_status="active",
            trial_status="converted",
            cancellation_status="none",
            created_at=_clock(),
            updated_at=_clock(),
        )
    )

    result = await CheckPlanLimits(plans=plans, subscriptions=subscriptions).execute(
        academy_id="academy-1",
        usage=PlatformUsage(
            active_students=251,
            locations=2,
            staff_members=13,
        ),
    )

    assert result.allowed is False
    assert result.violations == [
        "active_students exceeds plan limit 250",
        "staff_members exceeds plan limit 12",
    ]
    assert result.limits.max_locations == 2
