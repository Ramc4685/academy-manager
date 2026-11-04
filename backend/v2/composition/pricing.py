"""Composition for the admin Pricing page (``/admin/pricing``, Settings overhaul PR 11b).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, and the audit entries take
``academy_id`` from the request claims.

PR 26 adds "Change a plan price": preview, schedule, cancel, the
admin-readable list of classes with a scheduled fee, and the scheduler step
that moves fees and plan price once the month starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.plan_price_changes import (
    ApplyDuePlanPriceChanges,
    CancelPlanPriceChange,
    ListScheduledClassFees,
    PreviewPlanPriceChange,
    SchedulePlanPriceChange,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    GetPricingOverview,
    LinkMatchingClasses,
    SetClassPlanLink,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    MongoAcademyBillingMonth,
    MongoInvoicedPeriodReader,
    MongoPlanPriceChangeRepository,
    MongoPriceChangeFlipWriter,
)
from backend.v2.contexts.billing.infrastructure.mongo_pricing_read_model import (
    MongoClassPlanLinkRepository,
    MongoPricingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)


@dataclass(frozen=True)
class AdminPricing:
    """What ``interfaces/admin/pricing_routes.py`` reads off app.state."""

    overview: GetPricingOverview
    set_link: SetClassPlanLink
    link_matching: LinkMatchingClasses
    preview_price_change: PreviewPlanPriceChange
    schedule_price_change: SchedulePlanPriceChange
    cancel_price_change: CancelPlanPriceChange
    scheduled_class_fees: ListScheduledClassFees
    #: Scheduler only (``main.py`` monthly invoice job), never a route.
    apply_due_price_changes: ApplyDuePlanPriceChanges


def compose_admin_pricing(db: Any) -> AdminPricing:
    session_types = MongoSessionTypeRepository(db)
    read_model = MongoPricingReadModel(db)
    links = MongoClassPlanLinkRepository(db)
    audit = RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db))
    changes = MongoPlanPriceChangeRepository(db)
    current_period = MongoAcademyBillingMonth(db).current_period
    invoiced = MongoInvoicedPeriodReader(db)
    preview = PreviewPlanPriceChange(
        session_types=session_types,
        read_model=read_model,
        links=links,
        changes=changes,
        invoiced=invoiced,
        current_period=current_period,
    )
    return AdminPricing(
        overview=GetPricingOverview(
            session_types=session_types,
            read_model=read_model,
            links=links,
            price_changes=changes,
        ),
        set_link=SetClassPlanLink(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            price_changes=changes,
            charges=invoiced,
        ),
        link_matching=LinkMatchingClasses(
            session_types=session_types,
            read_model=read_model,
            links=links,
            audit=audit,
            price_changes=changes,
            charges=invoiced,
        ),
        preview_price_change=preview,
        schedule_price_change=SchedulePlanPriceChange(
            preview=preview, changes=changes, audit=audit
        ),
        cancel_price_change=CancelPlanPriceChange(
            changes=changes, current_period=current_period, audit=audit, charges=invoiced
        ),
        scheduled_class_fees=ListScheduledClassFees(changes=changes, read_model=read_model),
        apply_due_price_changes=ApplyDuePlanPriceChanges(
            changes=changes, flips=MongoPriceChangeFlipWriter(db), audit=audit
        ),
    )
