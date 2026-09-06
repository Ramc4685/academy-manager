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
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


def compose_admin_collections(db: Any) -> MongoCollectionsReadModel:
    return MongoCollectionsReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
    )
