"""Tenant-scoped BillingSettings storage."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoBillingSettingsRepository(TenantScopedRepository):
    collection_name = "billing_settings"

    async def get(self) -> BillingSettings:
        """Return this academy's billing settings, or fail-safe defaults if none exist."""
        doc = await self._find_one()
        academy_id = current_academy_id()
        if not doc:
            return BillingSettings.default(academy_id)
        doc = dict(doc)
        doc.pop("_id", None)
        doc.setdefault("academy_id", academy_id)
        return BillingSettings.model_validate(doc)

    async def upsert(self, settings: BillingSettings) -> None:
        payload = settings.model_dump(mode="python")
        payload.pop("academy_id", None)
        await self._update_one(
            {},
            {"$set": payload},
            upsert=True,
        )
