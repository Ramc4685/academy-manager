"""Tenant-scoped BillingSettings storage."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import InvoicePrefixTaken
from backend.v2.contexts.billing.infrastructure.house_academy import platform_charges_allowed
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

#: Fields only the platform may write; see ``set_application_fee_bps`` and
#: ``set_invoice_number_prefix``. Excluding the prefix also stops the tenant
#: write from persisting a default into every academy's document, which is how
#: "BLNO" used to spread (roadmap X32).
_PLATFORM_ONLY_FIELDS = {"application_fee_bps", "invoice_number_prefix"}

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

        ``application_fee_bps`` and ``invoice_number_prefix`` are deliberately
        NOT written here: they are set only by the platform, through
        :meth:`set_application_fee_bps` and :meth:`set_invoice_number_prefix`.
        Every academy-side settings write is read-modify-write through this
        method, so writing them here would let a stale read (or a forged
        model) overwrite the platform's values.
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

    async def set_invoice_number_prefix(self, prefix: str) -> None:
        """Platform write of this academy's invoice prefix (Settings overhaul P1 PR 2).

        Touches ONLY ``invoice_number_prefix``; creates the settings document
        when the academy has none yet. The caller validates the format
        (``domain.invoice_prefix``). Uniqueness across academies is the
        ``billing_settings_invoice_number_prefix_unique`` index (migration
        0206); a clash surfaces as ``InvoicePrefixTaken``.
        """
        try:
            await self._update_one(
                {},
                {"$set": {"invoice_number_prefix": prefix}},
                upsert=True,
            )
        except DuplicateKeyError as exc:
            # Only the prefix index means "taken". A clash on the one-doc-per-
            # academy index (two first-time upserts racing) is not about the
            # prefix, and mapping it would make AssignInvoicePrefix skip a
            # free prefix or the platform route return a false 409.
            key_pattern = (exc.details or {}).get("keyPattern") or {}
            if "invoice_number_prefix" not in key_pattern:
                raise
            raise InvoicePrefixTaken(
                "another academy already uses this invoice prefix", invoice_prefix=prefix
            ) from exc
