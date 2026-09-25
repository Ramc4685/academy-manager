"""Tenant-scoped BillingSettings storage."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.infrastructure.house_academy import platform_charges_allowed
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

#: Fields only the platform may write; see ``set_application_fee_bps``.
_PLATFORM_ONLY_FIELDS = {"application_fee_bps"}

#: Fields computed on read and never written by the app. The platform-charge
#: flag comes from the house-academy setting (see ``house_academy``); writing
#: the derived value back would let a read-modify-write persist it.
_DERIVED_FIELDS = {"allow_platform_charge_fallback"}


class MongoBillingSettingsRepository(TenantScopedRepository):
    collection_name = "billing_settings"

    async def get(self) -> BillingSettings:
        """Return this academy's billing settings, or fail-safe defaults if none exist."""
        doc = await self._find_one()
        academy_id = current_academy_id()
        if not doc:
            doc = BillingSettings.default(academy_id).model_dump(mode="python")
        doc = dict(doc)
        doc.pop("_id", None)
        doc.setdefault("academy_id", academy_id)
        doc["allow_platform_charge_fallback"] = platform_charges_allowed(
            academy_id, bool(doc.get("allow_platform_charge_fallback", False))
        )
        return BillingSettings.model_validate(doc)

    async def upsert(self, settings: BillingSettings) -> None:
        """Persist the academy-editable settings.

        ``allow_platform_charge_fallback`` is never written: it is derived on
        read from the house-academy setting.

        ``application_fee_bps`` is deliberately NOT written here: it is set
        only by a platform admin through :meth:`set_application_fee_bps`. Every
        academy-side settings write is read-modify-write through this method,
        so writing the field here would let a stale read (or a forged model)
        overwrite the platform's fee.
        """
        payload = settings.model_dump(
            mode="python", exclude=_PLATFORM_ONLY_FIELDS | _DERIVED_FIELDS
        )
        payload.pop("academy_id", None)
        await self._update_one(
            {},
            {"$set": payload},
            upsert=True,
        )

    async def set_application_fee_bps(self, fee_bps: int) -> None:
        """Platform-admin write of this academy's application fee (roadmap L9b).

        Touches ONLY ``application_fee_bps``; creates the settings document
        (every other field at its default) when the academy has none yet.
        """
        # Validate through the model so the bounds live in one place.
        BillingSettings(academy_id=current_academy_id(), application_fee_bps=fee_bps)
        await self._update_one(
            {},
            {"$set": {"application_fee_bps": int(fee_bps)}},
            upsert=True,
        )
