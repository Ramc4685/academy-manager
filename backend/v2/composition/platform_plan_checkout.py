"""Composition for the Growth tier (AI strategy Phase 2, slice A2).

``compose_admin_plan`` wires ``interfaces/admin/plan_routes.py`` (attached at
``app.state.admin_plan``); ``compose_platform_plan_sync`` builds the webhook
projection that ``HandleWebhookEvent`` hands ``source == "platform_plan"``
events to. Both read the tenant at execution time: the ledger volume read
uses the request's or the webhook drain's ``tenant_scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.v2.composition.academy_links import (
    AcademyBaseUrl,
    academy_frontend_base_url_lookup,
)
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.platform.audit.application.use_cases import PlatformAuditService
from backend.v2.contexts.platform.audit.infrastructure.mongo_platform_audit_repo import (
    MongoPlatformAuditRepository,
)
from backend.v2.contexts.platform.billing.application.use_cases.plan_checkout import (
    GetPlanOverview,
    StartGrowthCheckout,
    StripeVolumeReader,
    SyncTenantSubscriptionFromStripe,
)
from backend.v2.contexts.platform.billing.infrastructure.mongo_repositories import (
    MongoPlatformPlanRepository,
    MongoTenantSubscriptionRepository,
)


@dataclass(frozen=True)
class AdminPlan:
    get_overview: GetPlanOverview
    start_checkout: StartGrowthCheckout
    academy_frontend_base_url: AcademyBaseUrl
    academy_name: Any


def _stripe_volume(db: Any) -> StripeVolumeReader:
    ledger = MongoBillingLedgerRepository(db)

    async def volume(since: datetime) -> int:
        return await ledger.sum_stripe_settled_cents(since=since)

    return volume


def compose_admin_plan(db: Any, stripe: StripeGateway, settings: Any) -> AdminPlan:
    academies = MongoAcademyRepository(db)

    async def academy_name(academy_id: str) -> str:
        doc = await academies.find_by_id(academy_id)
        return str((doc or {}).get("display_name") or (doc or {}).get("name") or academy_id)

    return AdminPlan(
        get_overview=GetPlanOverview(
            plans=MongoPlatformPlanRepository(db),
            subscriptions=MongoTenantSubscriptionRepository(db),
        ),
        start_checkout=StartGrowthCheckout(
            plans=MongoPlatformPlanRepository(db),
            subscriptions=MongoTenantSubscriptionRepository(db),
            stripe=stripe,
            stripe_volume=_stripe_volume(db),
            audit_recorder=PlatformAuditService(
                audit_events=MongoPlatformAuditRepository(db)
            ).record_event,
        ),
        academy_frontend_base_url=academy_frontend_base_url_lookup(
            db, frontend_url=settings.frontend_url
        ),
        academy_name=academy_name,
    )


def compose_platform_plan_sync(db: Any) -> SyncTenantSubscriptionFromStripe:
    return SyncTenantSubscriptionFromStripe(
        plans=MongoPlatformPlanRepository(db),
        subscriptions=MongoTenantSubscriptionRepository(db),
        stripe_volume=_stripe_volume(db),
        audit_recorder=PlatformAuditService(
            audit_events=MongoPlatformAuditRepository(db)
        ).record_event,
    )
