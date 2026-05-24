"""Application use cases for SaaS platform billing."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.billing.application.ports import (
    PlatformPlanRepository,
    TenantSubscriptionRepository,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlanStatus,
    PlatformPlan,
    TenantSubscription,
)
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

AuditRecorder = Callable[[RecordPlatformAuditEventCommand], Awaitable[object]]


class PlatformPlanNotFound(DomainError):
    code = "PlatformBilling.PlanNotFound"
    status_code = 404


class PlatformPlanInactive(DomainError):
    code = "PlatformBilling.PlanInactive"
    status_code = 409


class TenantSubscriptionNotFound(DomainError):
    code = "PlatformBilling.SubscriptionNotFound"
    status_code = 404


class UpsertPlatformPlanCommand(BaseModel):
    plan_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    monthly_price_cents: int = Field(ge=0)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    limits: PlanLimits
    status: PlanStatus = "active"
    stripe_price_id: str | None = None


class StartTenantTrialCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    trial_ends_at: datetime
    actor_user_id: str | None = Field(default=None, min_length=1)
    actor_membership_id: str | None = None
    platform_actor_role: str | None = None
    request_id: str | None = None
    ip_address: str | None = None


class ActivateTenantSubscriptionCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    stripe_customer_id: str = Field(min_length=1)
    stripe_subscription_id: str = Field(min_length=1)
    current_period_start: datetime
    current_period_end: datetime


class ScheduleTenantCancellationCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    cancel_at_period_end: bool = True


class PlatformUsage(BaseModel):
    active_students: int = Field(ge=0)
    locations: int = Field(ge=0)
    staff_members: int = Field(ge=0)


class PlanLimitReport(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    plan_id: str
    limits: PlanLimits
    usage: PlatformUsage
    allowed: bool
    violations: list[str]


class ListPlatformPlans:
    def __init__(self, *, plans: PlatformPlanRepository) -> None:
        self._plans = plans

    async def execute(self) -> list[PlatformPlan]:
        return await self._plans.list()


class UpsertPlatformPlan:
    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: UpsertPlatformPlanCommand) -> PlatformPlan:
        now = self._clock()
        existing = await self._plans.get(command.plan_id)
        plan = PlatformPlan(
            plan_id=command.plan_id,
            code=command.code,
            display_name=command.display_name,
            monthly_price_cents=command.monthly_price_cents,
            currency=command.currency.lower(),
            limits=command.limits,
            status=command.status,
            stripe_price_id=command.stripe_price_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        await self._plans.save(plan)
        return plan


class StartTenantTrial:
    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_recorder: AuditRecorder | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._id_factory = id_factory or (lambda: f"platform_sub_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._audit_recorder = audit_recorder

    async def execute(self, command: StartTenantTrialCommand) -> TenantSubscription:
        plan = await _require_active_plan(self._plans, command.plan_id)
        now = self._clock()
        if command.trial_ends_at <= now:
            raise ValueError("trial_ends_at must be in the future")

        existing = await self._subscriptions.get_for_academy(command.academy_id)
        subscription_id = existing.subscription_id if existing else self._id_factory()
        created_at = existing.created_at if existing else now
        subscription = TenantSubscription(
            subscription_id=subscription_id,
            academy_id=command.academy_id,
            plan_id=plan.plan_id,
            billing_status="trialing",
            trial_status="active",
            cancellation_status="none",
            trial_started_at=now,
            trial_ends_at=command.trial_ends_at,
            cancel_at_period_end=False,
            cancelled_at=None,
            created_at=created_at,
            updated_at=now,
        )
        await self._subscriptions.save(subscription)
        await self._emit_audit(command=command, before=existing, after=subscription)
        return subscription

    async def _emit_audit(
        self,
        *,
        command: StartTenantTrialCommand,
        before: TenantSubscription | None,
        after: TenantSubscription,
    ) -> None:
        if self._audit_recorder is None or command.actor_user_id is None:
            return
        try:
            await self._audit_recorder(
                RecordPlatformAuditEventCommand(
                    actor_user_id=command.actor_user_id,
                    actor_membership_id=command.actor_membership_id,
                    academy_id=command.academy_id,
                    platform_actor_role=command.platform_actor_role,
                    action="platform_billing.trial_started",
                    entity_type="tenant_subscription",
                    entity_id=after.subscription_id,
                    before_snapshot=before.model_dump(mode="json") if before else None,
                    after_snapshot=after.model_dump(mode="json"),
                    request_id=command.request_id,
                    ip_address=command.ip_address,
                )
            )
        except Exception as exc:
            log.warning(
                "platform_billing_audit_emit_failed action=%s academy=%s err=%s",
                "platform_billing.trial_started",
                command.academy_id,
                exc,
            )


class ActivateTenantSubscription:
    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._id_factory = id_factory or (lambda: f"platform_sub_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: ActivateTenantSubscriptionCommand) -> TenantSubscription:
        plan = await _require_active_plan(self._plans, command.plan_id)
        now = self._clock()
        existing = await self._subscriptions.get_for_academy(command.academy_id)
        subscription = _active_subscription(
            existing=existing,
            subscription_id=self._id_factory(),
            academy_id=command.academy_id,
            plan=plan,
            stripe_customer_id=command.stripe_customer_id,
            stripe_subscription_id=command.stripe_subscription_id,
            current_period_start=command.current_period_start,
            current_period_end=command.current_period_end,
            now=now,
        )
        await self._subscriptions.save(subscription)
        return subscription


class ScheduleTenantCancellation:
    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: ScheduleTenantCancellationCommand) -> TenantSubscription:
        existing = await self._subscriptions.get_for_academy(command.academy_id)
        if existing is None:
            raise TenantSubscriptionNotFound(
                f"no platform subscription for academy {command.academy_id}"
            )
        await _require_active_plan(self._plans, existing.plan_id)

        now = self._clock()
        if command.cancel_at_period_end:
            updated = existing.model_copy(
                update={
                    "cancellation_status": "scheduled",
                    "cancel_at_period_end": True,
                    "updated_at": now,
                }
            )
        else:
            updated = existing.model_copy(
                update={
                    "billing_status": "cancelled",
                    "cancellation_status": "cancelled",
                    "cancel_at_period_end": False,
                    "cancelled_at": now,
                    "updated_at": now,
                }
            )
        await self._subscriptions.save(updated)
        return updated


class CheckPlanLimits:
    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions

    async def execute(self, *, academy_id: str, usage: PlatformUsage) -> PlanLimitReport:
        subscription = await self._subscriptions.get_for_academy(academy_id)
        if subscription is None:
            raise TenantSubscriptionNotFound(f"no platform subscription for academy {academy_id}")
        plan = await _require_active_plan(self._plans, subscription.plan_id)
        violations = _limit_violations(plan.limits, usage)
        return PlanLimitReport(
            academy_id=academy_id,
            plan_id=plan.plan_id,
            limits=plan.limits,
            usage=usage,
            allowed=not violations,
            violations=violations,
        )


class GetTenantSubscription:
    def __init__(self, *, subscriptions: TenantSubscriptionRepository) -> None:
        self._subscriptions = subscriptions

    async def execute(self, academy_id: str) -> TenantSubscription:
        subscription = await self._subscriptions.get_for_academy(academy_id)
        if subscription is None:
            raise TenantSubscriptionNotFound(f"no platform subscription for academy {academy_id}")
        return subscription


@dataclass(frozen=True)
class PlatformBillingUseCases:
    list_plans: ListPlatformPlans
    upsert_plan: UpsertPlatformPlan
    get_subscription: GetTenantSubscription
    start_trial: StartTenantTrial
    activate_subscription: ActivateTenantSubscription
    schedule_cancellation: ScheduleTenantCancellation
    check_limits: CheckPlanLimits


async def _require_active_plan(plans: PlatformPlanRepository, plan_id: str) -> PlatformPlan:
    plan = await plans.get(plan_id)
    if plan is None:
        raise PlatformPlanNotFound(f"platform plan not found: {plan_id}")
    if not plan.is_active:
        raise PlatformPlanInactive(f"platform plan is not active: {plan_id}")
    return plan


def _active_subscription(
    *,
    existing: TenantSubscription | None,
    subscription_id: str,
    academy_id: str,
    plan: PlatformPlan,
    stripe_customer_id: str,
    stripe_subscription_id: str,
    current_period_start: datetime,
    current_period_end: datetime,
    now: datetime,
) -> TenantSubscription:
    created_at = existing.created_at if existing else now
    resolved_subscription_id = existing.subscription_id if existing else subscription_id
    trial_status = "converted" if existing and existing.trial_status == "active" else "none"
    return TenantSubscription(
        subscription_id=resolved_subscription_id,
        academy_id=academy_id,
        plan_id=plan.plan_id,
        billing_status="active",
        trial_status=trial_status,
        cancellation_status="none",
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        trial_started_at=existing.trial_started_at if existing else None,
        trial_ends_at=existing.trial_ends_at if existing else None,
        cancel_at_period_end=False,
        cancelled_at=None,
        created_at=created_at,
        updated_at=now,
    )


def _limit_violations(limits: PlanLimits, usage: PlatformUsage) -> list[str]:
    checks = (
        ("active_students", usage.active_students, limits.max_active_students),
        ("locations", usage.locations, limits.max_locations),
        ("staff_members", usage.staff_members, limits.max_staff_members),
    )
    return [
        f"{name} exceeds plan limit {limit}"
        for name, value, limit in checks
        if limit is not None and value > limit
    ]
