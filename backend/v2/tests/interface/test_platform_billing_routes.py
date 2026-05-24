"""Interface tests for platform SaaS billing routes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ActivateTenantSubscription,
    CheckPlanLimits,
    GetTenantSubscription,
    ListPlatformPlans,
    ScheduleTenantCancellation,
    StartTenantTrial,
    UpsertPlatformPlan,
)
from backend.v2.contexts.platform.billing.domain.models import PlatformPlan, TenantSubscription
from backend.v2.interfaces.platform.billing_routes import (
    PlatformBillingUseCases,
    get_platform_billing,
)
from backend.v2.interfaces.platform.billing_routes import (
    router as billing_router,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class FakePlanRepository:
    def __init__(self) -> None:
        self.by_id: dict[str, PlatformPlan] = {}

    async def get(self, plan_id: str) -> PlatformPlan | None:
        return self.by_id.get(plan_id)

    async def list(self) -> list[PlatformPlan]:
        return sorted(self.by_id.values(), key=lambda plan: plan.code)

    async def save(self, plan: PlatformPlan) -> None:
        self.by_id[plan.plan_id] = plan


class FakeTenantSubscriptionRepository:
    def __init__(self) -> None:
        self.by_academy: dict[str, TenantSubscription] = {}

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        return self.by_academy.get(academy_id)

    async def save(self, subscription: TenantSubscription) -> None:
        self.by_academy[subscription.academy_id] = subscription


class FakePlatformAuditRecorder:
    def __init__(self) -> None:
        self.commands: list[RecordPlatformAuditEventCommand] = []

    async def record_event(self, command: RecordPlatformAuditEventCommand) -> None:
        self.commands.append(command)


def _clock() -> datetime:
    return datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _platform_admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _academy_admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="academy-admin",
        email="admin@example.com",
        academy_id="academy-1",
        membership_id="membership-1",
        roles=("admin",),
    )


def _billing_use_cases(
    plans: FakePlanRepository,
    subscriptions: FakeTenantSubscriptionRepository,
    audit: FakePlatformAuditRecorder | None = None,
) -> PlatformBillingUseCases:
    return PlatformBillingUseCases(
        list_plans=ListPlatformPlans(plans=plans),
        upsert_plan=UpsertPlatformPlan(
            plans=plans,
            clock=_clock,
            audit_recorder=audit.record_event if audit else None,
        ),
        get_subscription=GetTenantSubscription(subscriptions=subscriptions),
        start_trial=StartTenantTrial(
            plans=plans,
            subscriptions=subscriptions,
            id_factory=lambda: "platform-sub-1",
            clock=_clock,
            audit_recorder=audit.record_event if audit else None,
        ),
        activate_subscription=ActivateTenantSubscription(
            plans=plans,
            subscriptions=subscriptions,
            id_factory=lambda: "platform-sub-unused",
            clock=_clock,
            audit_recorder=audit.record_event if audit else None,
        ),
        schedule_cancellation=ScheduleTenantCancellation(
            plans=plans,
            subscriptions=subscriptions,
            clock=_clock,
            audit_recorder=audit.record_event if audit else None,
        ),
        check_limits=CheckPlanLimits(plans=plans, subscriptions=subscriptions),
    )


def _app(
    claims: AuthClaims,
) -> tuple[
    FastAPI,
    FakePlanRepository,
    FakeTenantSubscriptionRepository,
    FakePlatformAuditRecorder,
]:
    plans = FakePlanRepository()
    subscriptions = FakeTenantSubscriptionRepository()
    audit = FakePlatformAuditRecorder()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(billing_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_platform_billing] = lambda: _billing_use_cases(
        plans,
        subscriptions,
        audit,
    )
    return app, plans, subscriptions, audit


@contextmanager
def _client(
    claims: AuthClaims,
) -> Iterator[tuple[TestClient, FakePlanRepository, FakePlatformAuditRecorder]]:
    app, plans, _subscriptions, audit = _app(claims)
    with TestClient(app) as client:
        yield client, plans, audit


def _plan_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": "growth",
        "display_name": "Growth",
        "monthly_price_cents": 29900,
        "currency": "usd",
        "limits": {
            "max_active_students": 250,
            "max_locations": 2,
            "max_staff_members": 12,
        },
        "status": "active",
        "stripe_price_id": "price_platform_growth",
    }
    payload.update(overrides)
    return payload


def test_platform_admin_can_manage_billing_lifecycle_routes() -> None:
    with _client(_platform_admin_claims()) as (client, _plans, _audit):
        created_plan = client.put(
            "/api/v2/platform/billing/plans/plan-growth",
            json=_plan_payload(),
        )
        listed_plans = client.get("/api/v2/platform/billing/plans")
        trial = client.post(
            "/api/v2/platform/billing/tenants/academy-1/trial",
            json={
                "plan_id": "plan-growth",
                "trial_ends_at": (_clock() + timedelta(days=14)).isoformat(),
            },
        )
        activated = client.post(
            "/api/v2/platform/billing/tenants/academy-1/activate-subscription",
            json={
                "plan_id": "plan-growth",
                "stripe_customer_id": "cus_platform_123",
                "stripe_subscription_id": "sub_platform_123",
                "current_period_start": _clock().isoformat(),
                "current_period_end": (_clock() + timedelta(days=30)).isoformat(),
            },
        )
        subscription = client.get("/api/v2/platform/billing/tenants/academy-1/subscription")
        limits = client.post(
            "/api/v2/platform/billing/tenants/academy-1/check-limits",
            json={"active_students": 251, "locations": 2, "staff_members": 13},
        )
        scheduled = client.post(
            "/api/v2/platform/billing/tenants/academy-1/schedule-cancellation",
        )
        cancelled = client.post("/api/v2/platform/billing/tenants/academy-1/cancel-now")

    assert created_plan.status_code == 200, created_plan.text
    assert created_plan.json()["plan_id"] == "plan-growth"
    assert listed_plans.status_code == 200, listed_plans.text
    assert [plan["plan_id"] for plan in listed_plans.json()] == ["plan-growth"]
    assert trial.status_code == 200, trial.text
    assert trial.json()["billing_status"] == "trialing"
    assert activated.status_code == 200, activated.text
    assert activated.json()["stripe_customer_id"] == "cus_platform_123"
    assert activated.json()["stripe_subscription_id"] == "sub_platform_123"
    assert subscription.status_code == 200, subscription.text
    assert subscription.json()["billing_status"] == "active"
    assert limits.status_code == 200, limits.text
    assert limits.json()["allowed"] is False
    assert limits.json()["violations"] == [
        "active_students exceeds plan limit 250",
        "staff_members exceeds plan limit 12",
    ]
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["cancellation_status"] == "scheduled"
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["billing_status"] == "cancelled"


def test_academy_admin_cannot_access_platform_billing_routes() -> None:
    with _client(_academy_admin_claims()) as (client, _plans, _audit):
        list_response = client.get("/api/v2/platform/billing/plans")
        create_response = client.put(
            "/api/v2/platform/billing/plans/plan-growth",
            json=_plan_payload(),
        )
        subscription_response = client.get(
            "/api/v2/platform/billing/tenants/academy-1/subscription",
        )

    assert list_response.status_code == 404
    assert create_response.status_code == 404
    assert subscription_response.status_code == 404


def test_start_trial_route_emits_unified_platform_audit_event() -> None:
    with _client(_platform_admin_claims()) as (client, _plans, audit):
        created_plan = client.put(
            "/api/v2/platform/billing/plans/plan-growth",
            json=_plan_payload(),
        )
        audit.commands.clear()
        trial = client.post(
            "/api/v2/platform/billing/tenants/academy-1/trial",
            json={
                "plan_id": "plan-growth",
                "trial_ends_at": (_clock() + timedelta(days=14)).isoformat(),
            },
            headers={"x-request-id": "req-platform-billing-1"},
        )

    assert created_plan.status_code == 200, created_plan.text
    assert trial.status_code == 200, trial.text
    assert len(audit.commands) == 1
    event = audit.commands[0]
    assert event.actor_user_id == "platform-admin"
    assert event.actor_membership_id is None
    assert event.platform_actor_role == "platform_admin"
    assert event.academy_id == "academy-1"
    assert event.action == "platform_billing.trial_started"
    assert event.entity_type == "tenant_subscription"
    assert event.entity_id == "platform-sub-1"
    assert event.before_snapshot is None
    assert event.after_snapshot is not None
    assert event.after_snapshot["plan_id"] == "plan-growth"
    assert event.request_id == "req-platform-billing-1"


def test_billing_write_routes_emit_one_unified_platform_audit_event_each() -> None:
    with _client(_platform_admin_claims()) as (client, _plans, audit):
        created_plan = client.put(
            "/api/v2/platform/billing/plans/plan-growth",
            json=_plan_payload(),
            headers={"x-request-id": "req-plan"},
        )
        trial = client.post(
            "/api/v2/platform/billing/tenants/academy-1/trial",
            json={
                "plan_id": "plan-growth",
                "trial_ends_at": (_clock() + timedelta(days=14)).isoformat(),
            },
            headers={"x-request-id": "req-trial"},
        )
        activated = client.post(
            "/api/v2/platform/billing/tenants/academy-1/activate-subscription",
            json={
                "plan_id": "plan-growth",
                "stripe_customer_id": "cus_platform_123",
                "stripe_subscription_id": "sub_platform_123",
                "current_period_start": _clock().isoformat(),
                "current_period_end": (_clock() + timedelta(days=30)).isoformat(),
            },
            headers={"x-request-id": "req-activate"},
        )
        scheduled = client.post(
            "/api/v2/platform/billing/tenants/academy-1/schedule-cancellation",
            headers={"x-request-id": "req-schedule"},
        )
        cancelled = client.post(
            "/api/v2/platform/billing/tenants/academy-1/cancel-now",
            headers={"x-request-id": "req-cancel"},
        )

    assert created_plan.status_code == 200, created_plan.text
    assert trial.status_code == 200, trial.text
    assert activated.status_code == 200, activated.text
    assert scheduled.status_code == 200, scheduled.text
    assert cancelled.status_code == 200, cancelled.text
    assert [event.action for event in audit.commands] == [
        "platform_billing.plan_upserted",
        "platform_billing.trial_started",
        "platform_billing.subscription_activated",
        "platform_billing.cancellation_scheduled",
        "platform_billing.subscription_cancelled",
    ]
    assert [event.request_id for event in audit.commands] == [
        "req-plan",
        "req-trial",
        "req-activate",
        "req-schedule",
        "req-cancel",
    ]
    assert all(event.actor_user_id == "platform-admin" for event in audit.commands)
    assert all(event.platform_actor_role == "platform_admin" for event in audit.commands)
