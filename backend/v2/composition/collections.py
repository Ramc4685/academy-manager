"""Composition for the admin Payments bucket view (``GET /admin/payments/collections``).

Lives outside ``composition/admin.py`` because that module sits at its
wiring line budget. Pure wiring: the read model resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.infrastructure.collections_read_model import (
    MongoCollectionsReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.tenancy.academy_url import academy_frontend_url
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


def _parent_payments_link(db: Any) -> Any:
    """Resolve one academy's parent-payments URL and display name.

    The same two facts ``list_dues_followup`` resolved for its WhatsApp link,
    wired here so the billing read model never reaches into identity itself.
    Outbound links must point at the academy's own subdomain (ADR-0007).
    """
    academies = MongoAcademyRepository(db)

    async def resolve(academy_id: str) -> tuple[str | None, str]:
        doc = await academies.find_by_id(academy_id)
        slug = str(doc.get("slug") or "") if doc else ""
        name = str(doc.get("display_name") or doc.get("name") or "") if doc else ""
        frontend_url = academy_frontend_url(
            frontend_url=get_settings().frontend_url, academy_slug=slug
        )
        return (f"{frontend_url}/parent/payments" if frontend_url else None), name

    return resolve


def compose_admin_collections(db: Any) -> MongoCollectionsReadModel:
    return MongoCollectionsReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        parent_payments_link=_parent_payments_link(db),
    )
