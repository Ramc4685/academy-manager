"""Composition helpers for SaaS platform billing infrastructure."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.platform.audit.application.use_cases import PlatformAuditService
from backend.v2.contexts.platform.audit.infrastructure.mongo_platform_audit_repo import (
    MongoPlatformAuditRepository,
)
from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ActivateTenantSubscription,
    CheckPlanLimits,
    GetTenantSubscription,
    ListPlatformPlans,
    PlatformBillingUseCases,
    ScheduleTenantCancellation,
    StartTenantTrial,
    UpsertPlatformPlan,
)
from backend.v2.contexts.platform.billing.infrastructure.mongo_repositories import (
    MongoPlatformPlanRepository,
    MongoTenantSubscriptionRepository,
)


def build_platform_billing_use_cases(db: Any) -> PlatformBillingUseCases:
    plans = MongoPlatformPlanRepository(db)
    subscriptions = MongoTenantSubscriptionRepository(db)
    platform_audit = PlatformAuditService(
        audit_events=MongoPlatformAuditRepository(db),
    )
    return PlatformBillingUseCases(
        list_plans=ListPlatformPlans(plans=plans),
        upsert_plan=UpsertPlatformPlan(plans=plans),
        get_subscription=GetTenantSubscription(subscriptions=subscriptions),
        start_trial=StartTenantTrial(
            plans=plans,
            subscriptions=subscriptions,
            audit_recorder=platform_audit.record_event,
        ),
        activate_subscription=ActivateTenantSubscription(
            plans=plans,
            subscriptions=subscriptions,
        ),
        schedule_cancellation=ScheduleTenantCancellation(
            plans=plans,
            subscriptions=subscriptions,
        ),
        check_limits=CheckPlanLimits(plans=plans, subscriptions=subscriptions),
    )
