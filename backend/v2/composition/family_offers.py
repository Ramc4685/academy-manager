"""Composition for Settings -> Billing rules -> Family offers (L9 C1).

Outside ``composition/admin.py``, which sits at its line budget. The settings
repository resolves the tenant at execution time, so nothing tenant-specific
is captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.family_offers import (
    GetFamilyOffers,
    UpdateFamilyOffers,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    preview_family_sibling_discount,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)


@dataclass(frozen=True)
class AdminFamilyOffers:
    """What ``interfaces/admin/family_offers_routes.py`` reads off app.state."""

    read: GetFamilyOffers
    write: UpdateFamilyOffers
    sibling_preview: SiblingDiscountPreview


@dataclass(frozen=True)
class SiblingDiscountPreview:
    """Read-only: who gets the sibling discount on a family's month."""

    db: Any

    async def execute(self, parent_id: str) -> dict[str, Any]:
        return await preview_family_sibling_discount(
            self.db,
            parent_id=parent_id,
            now=datetime.now(UTC),
            discounts=MongoTuitionDiscountRepository(self.db),
        )


def compose_admin_family_offers(db: Any) -> AdminFamilyOffers:
    store = MongoBillingSettingsRepository(db)
    return AdminFamilyOffers(
        read=GetFamilyOffers(store=store),
        write=UpdateFamilyOffers(
            store=store,
            audit=RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db)),
        ),
        sibling_preview=SiblingDiscountPreview(db),
    )
