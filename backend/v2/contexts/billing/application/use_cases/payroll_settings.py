"""Coach payroll settings (L7): the owner's rules for percent-of-invoiced-tuition pay.

The four fields live on the academy's ``BillingSettings`` document (the money
settings section). A change is owner-only, validated at the API, audited
through ``RecordMoneySettingChange`` and read only when a payout period is
generated or recomputed, so approved and paid periods never move.
"""

from __future__ import annotations

from typing import Any, Protocol

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

PAYROLL_SETTING_FIELDS = (
    "payroll_ach_discount_reduces_base",
    "payroll_count_checkout_first_month",
    "payroll_cancelled_class_share",
    "payroll_missing_invoices",
)


class PayrollSettingsStore(Protocol):
    async def get(self) -> BillingSettings: ...

    async def upsert(self, settings: BillingSettings) -> None: ...


def payroll_settings_of(settings: BillingSettings) -> dict[str, Any]:
    return {field: getattr(settings, field) for field in PAYROLL_SETTING_FIELDS}


class GetPayrollSettings:
    def __init__(self, *, settings: PayrollSettingsStore) -> None:
        self._settings = settings

    async def execute(self) -> dict[str, Any]:
        return payroll_settings_of(await self._settings.get())


class UpdatePayrollSettings:
    def __init__(self, *, settings: PayrollSettingsStore, audit: RecordMoneySettingChange) -> None:
        self._settings = settings
        self._audit = audit

    async def execute(
        self, *, academy_id: str, actor_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        unknown = set(values) - set(PAYROLL_SETTING_FIELDS)
        if unknown:
            raise ValueError(f"not payroll settings: {sorted(unknown)}")
        current = await self._settings.get()
        # Validate through the model so the allowed values live in one place.
        updated = BillingSettings.model_validate({**current.model_dump(), **values})
        before, after = payroll_settings_of(current), payroll_settings_of(updated)
        if before == after:
            return after
        await self._settings.upsert(updated)
        await self._audit.execute(
            academy_id=academy_id,
            action="payroll_settings_changed",
            actor_id=actor_id,
            before=before,
            after=after,
            reason="Settings -> Billing rules -> Coach payroll",
        )
        return after
