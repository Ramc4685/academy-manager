"""Composition for the admin Pricing page (``/admin/pricing``, Settings overhaul PR 11b).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, and the audit entries take
``academy_id`` from the request claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    GetPricingOverview,
    LinkMatchingClasses,
    SetClassPlanLink,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
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


def compose_admin_pricing(db: Any) -> AdminPricing:
    session_types = MongoSessionTypeRepository(db)
    read_model = MongoPricingReadModel(db)
    links = MongoClassPlanLinkRepository(db)
    audit = RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db))
    return AdminPricing(
        overview=GetPricingOverview(
            session_types=session_types, read_model=read_model, links=links
        ),
        set_link=SetClassPlanLink(
            session_types=session_types, read_model=read_model, links=links, audit=audit
        ),
        link_matching=LinkMatchingClasses(
            session_types=session_types, read_model=read_model, links=links, audit=audit
        ),
    )
