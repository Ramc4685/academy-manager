from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ActivateTenantSubscription,
    ActivateTenantSubscriptionCommand,
    CheckPlanLimits,
    PlatformUsage,
    ScheduleTenantCancellation,
    ScheduleTenantCancellationCommand,
    StartTenantTrial,
    StartTenantTrialCommand,
    UpsertPlatformPlan,
    UpsertPlatformPlanCommand,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlatformPlan,
    TenantSubscription,
)
from backend.v2.contexts.platform.billing.infrastructure.composition import (
    build_platform_billing_use_cases,
)
from backend.v2.contexts.platform.billing.infrastructure.mongo_repositories import (
    MongoPlatformPlanRepository,
    MongoTenantSubscriptionRepository,
)


class FakePlanRepository:
    def __init__(self, plans: list[PlatformPlan]) -> None:
        self._plans = {plan.plan_id: plan for plan in plans}
        self.saved: list[PlatformPlan] = []

    async def get(self, plan_id: str) -> PlatformPlan | None:
        return self._plans.get(plan_id)

    async def save(self, plan: PlatformPlan) -> None:
        self.saved.append(plan)
        self._plans[plan.plan_id] = plan


class FakeTenantSubscriptionRepository:
    def __init__(self) -> None:
        self.saved: list[TenantSubscription] = []
        self.by_academy: dict[str, TenantSubscription] = {}

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        return self.by_academy.get(academy_id)

    async def save(self, subscription: TenantSubscription) -> None:
        self.saved.append(subscription)
        self.by_academy[subscription.academy_id] = subscription


class FakePlatformAuditRecorder:
    def __init__(self) -> None:
        self.commands: list[RecordPlatformAuditEventCommand] = []

    async def record_event(self, command: RecordPlatformAuditEventCommand) -> None:
        self.commands.append(command)


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
async def test_upsert_plan_emits_one_unified_platform_audit_event_after_save() -> None:
    plans = FakePlanRepository([])
    audit = FakePlatformAuditRecorder()

    result = await UpsertPlatformPlan(
        plans=plans,
        clock=_clock,
        audit_recorder=audit.record_event,
    ).execute(
        UpsertPlatformPlanCommand(
            plan_id="plan-growth",
            academy_id="platform-control",
            code="growth",
            display_name="Growth",
            monthly_price_cents=29_900,
            limits=PlanLimits(max_active_students=250),
            actor_user_id="platform-admin-1",
            platform_actor_role="platform_admin",
            request_id="req-plan",
            ip_address="203.0.113.10",
        )
    )

    assert plans.saved == [result]
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.actor_user_id == "platform-admin-1"
    assert event.platform_actor_role == "platform_admin"
    assert event.academy_id == "platform-control"
    assert event.action == "platform_billing.plan_upserted"
    assert event.entity_type == "platform_plan"
    assert event.entity_id == "plan-growth"
    assert event.before_snapshot is None
    assert event.after_snapshot is not None
    assert event.after_snapshot["monthly_price_cents"] == 29_900
    assert event.request_id == "req-plan"
    assert event.ip_address == "203.0.113.10"


@pytest.mark.asyncio
async def test_start_trial_emits_unified_platform_audit_event() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    audit = FakePlatformAuditRecorder()
    trial_ends_at = _clock() + timedelta(days=14)

    result = await StartTenantTrial(
        plans=plans,
        subscriptions=subscriptions,
        id_factory=lambda: "platform-sub-1",
        clock=_clock,
        audit_recorder=audit.record_event,
    ).execute(
        StartTenantTrialCommand(
            academy_id="academy-1",
            plan_id="plan-growth",
            trial_ends_at=trial_ends_at,
            actor_user_id="platform-admin-1",
            actor_membership_id="platform-membership-1",
            platform_actor_role="platform_admin",
            request_id="req-123",
            ip_address="203.0.113.10",
        )
    )

    assert result.subscription_id == "platform-sub-1"
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.actor_user_id == "platform-admin-1"
    assert event.actor_membership_id == "platform-membership-1"
    assert event.platform_actor_role == "platform_admin"
    assert event.academy_id == "academy-1"
    assert event.action == "platform_billing.trial_started"
    assert event.entity_type == "tenant_subscription"
    assert event.entity_id == "platform-sub-1"
    assert event.before_snapshot is None
    assert event.after_snapshot is not None
    assert event.after_snapshot["billing_status"] == "trialing"
    assert event.after_snapshot["trial_ends_at"] == "2026-06-15T12:00:00Z"
    assert event.request_id == "req-123"
    assert event.ip_address == "203.0.113.10"


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
async def test_activate_subscription_emits_one_unified_platform_audit_event_after_save() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    audit = FakePlatformAuditRecorder()
    existing = TenantSubscription(
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
    await subscriptions.save(existing)

    result = await ActivateTenantSubscription(
        plans=plans,
        subscriptions=subscriptions,
        id_factory=lambda: "platform-sub-unused",
        clock=_clock,
        audit_recorder=audit.record_event,
    ).execute(
        ActivateTenantSubscriptionCommand(
            academy_id="academy-1",
            plan_id="plan-growth",
            stripe_customer_id="cus_platform_123",
            stripe_subscription_id="sub_platform_123",
            current_period_start=_clock(),
            current_period_end=_clock() + timedelta(days=30),
            actor_user_id="platform-admin-1",
            actor_membership_id="platform-membership-1",
            platform_actor_role="platform_admin",
            request_id="req-activate",
            ip_address="203.0.113.10",
        )
    )

    assert subscriptions.saved[-1] == result
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.action == "platform_billing.subscription_activated"
    assert event.entity_type == "tenant_subscription"
    assert event.entity_id == "platform-sub-1"
    assert event.before_snapshot is not None
    assert event.before_snapshot["billing_status"] == "trialing"
    assert event.after_snapshot is not None
    assert event.after_snapshot["billing_status"] == "active"
    assert event.request_id == "req-activate"


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
async def test_schedule_cancellation_emits_one_unified_platform_audit_event_after_save() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    audit = FakePlatformAuditRecorder()
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
        audit_recorder=audit.record_event,
    ).execute(
        ScheduleTenantCancellationCommand(
            academy_id="academy-1",
            cancel_at_period_end=True,
            actor_user_id="platform-admin-1",
            platform_actor_role="platform_admin",
            request_id="req-schedule",
            ip_address="203.0.113.10",
        )
    )

    assert subscriptions.saved[-1] == result
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.action == "platform_billing.cancellation_scheduled"
    assert event.entity_id == "platform-sub-1"
    assert event.before_snapshot is not None
    assert event.before_snapshot["cancellation_status"] == "none"
    assert event.after_snapshot is not None
    assert event.after_snapshot["cancellation_status"] == "scheduled"
    assert event.request_id == "req-schedule"


@pytest.mark.asyncio
async def test_cancel_now_emits_one_unified_platform_audit_event_after_save() -> None:
    plans = FakePlanRepository([_plan()])
    subscriptions = FakeTenantSubscriptionRepository()
    audit = FakePlatformAuditRecorder()
    await subscriptions.save(
        TenantSubscription(
            subscription_id="platform-sub-1",
            academy_id="academy-1",
            plan_id="plan-growth",
            billing_status="active",
            trial_status="converted",
            cancellation_status="scheduled",
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
        audit_recorder=audit.record_event,
    ).execute(
        ScheduleTenantCancellationCommand(
            academy_id="academy-1",
            cancel_at_period_end=False,
            actor_user_id="platform-admin-1",
            platform_actor_role="platform_admin",
            request_id="req-cancel",
            ip_address="203.0.113.10",
        )
    )

    assert subscriptions.saved[-1] == result
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.action == "platform_billing.subscription_cancelled"
    assert event.entity_id == "platform-sub-1"
    assert event.before_snapshot is not None
    assert event.before_snapshot["billing_status"] == "active"
    assert event.after_snapshot is not None
    assert event.after_snapshot["billing_status"] == "cancelled"
    assert event.after_snapshot["cancelled_at"] == "2026-06-01T12:00:00Z"
    assert event.request_id == "req-cancel"


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


@pytest.mark.asyncio
async def test_mongo_repositories_persist_platform_plans_and_tenant_subscriptions() -> None:
    client = AsyncMongoMockClient()
    db = client["academy_manager_test"]
    plans = MongoPlatformPlanRepository(db)
    subscriptions = MongoTenantSubscriptionRepository(db)

    plan = _plan()
    subscription = TenantSubscription(
        subscription_id="platform-sub-1",
        academy_id="academy-1",
        plan_id=plan.plan_id,
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

    await plans.save(plan)
    await subscriptions.save(subscription)

    stored_plan = await plans.get(plan.plan_id)
    listed_plans = await plans.list()
    stored_subscription = await subscriptions.get_for_academy("academy-1")

    assert stored_plan == plan
    assert listed_plans == [plan]
    assert stored_subscription == subscription
    assert await db["subscriptions"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_composed_start_trial_writes_platform_audit_events_collection() -> None:
    client = AsyncMongoMockClient()
    db = client["academy_manager_test"]
    use_cases = build_platform_billing_use_cases(db)
    await use_cases.upsert_plan.execute(
        UpsertPlatformPlanCommand(
            plan_id="plan-growth",
            code="growth",
            display_name="Growth",
            monthly_price_cents=29_900,
            limits=PlanLimits(
                max_active_students=250,
                max_locations=2,
                max_staff_members=12,
            ),
            status="active",
        )
    )

    await use_cases.start_trial.execute(
        StartTenantTrialCommand(
            academy_id="academy-1",
            plan_id="plan-growth",
            trial_ends_at=datetime.now(UTC) + timedelta(days=14),
            actor_user_id="platform-admin-1",
            platform_actor_role="platform_admin",
        )
    )

    audit_doc = await db["platform_audit_events"].find_one(
        {"action": "platform_billing.trial_started"}
    )
    assert audit_doc is not None
    assert audit_doc["actor_user_id"] == "platform-admin-1"
    assert audit_doc["platform_actor_role"] == "platform_admin"
    assert audit_doc["academy_id"] == "academy-1"
    assert audit_doc["entity_type"] == "tenant_subscription"
    assert audit_doc["after_snapshot"]["billing_status"] == "trialing"
