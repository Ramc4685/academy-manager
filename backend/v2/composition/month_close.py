"""Composition for the admin Month close view (``GET /admin/reports/month-close``).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget, exactly as ``composition/collections.py`` does. Pure wiring: the
read model resolves the tenant from ``current_academy_id()`` at request time,
so nothing tenant-specific is captured here.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.finance import (
    MongoTuitionDiscountSummaryQuery,
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
from backend.v2.contexts.billing.infrastructure.month_close_read_model import (
    MongoMonthCloseReadModel,
)
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


def compose_admin_month_close(db: Any) -> MongoMonthCloseReadModel:
    return MongoMonthCloseReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        # The same query behind ``GET /admin/finance/tuition-discounts``; the
        # card on Month close must never be a second implementation of it.
        tuition_discounts=MongoTuitionDiscountSummaryQuery(db),
    )
