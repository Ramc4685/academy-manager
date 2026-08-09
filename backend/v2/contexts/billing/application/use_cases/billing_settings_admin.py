"""Admin billing-settings operations.

``allow_platform_charge_fallback`` is the TEMPORARY escape hatch that lets
checkout/invoice/autopay charge the platform Stripe account while the
academy's connected account isn't charge-ready (see
``domain.billing_settings.BillingSettings``). Until now it was only settable
by a manual Mongo write; these use cases give admins a guarded, audited
toggle.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import BillingSettingsRepository
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.shared.ids import new_ulid


class BillingAuditAppender(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


class SetPlatformChargeFallbackCommand(BaseModel):
    model_config = {"frozen": True}

    enabled: bool
    actor_id: str
    reason: str | None = None


class PlatformChargeFallbackResult(BaseModel):
    model_config = {"frozen": True}

    allow_platform_charge_fallback: bool


class GetPlatformChargeFallback:
    def __init__(self, *, settings: BillingSettingsRepository) -> None:
        self._settings = settings

    async def execute(self) -> PlatformChargeFallbackResult:
        current = await self._settings.get()
        return PlatformChargeFallbackResult(
            allow_platform_charge_fallback=current.allow_platform_charge_fallback
        )


class SetPlatformChargeFallback:
    """Flip ``billing_settings.allow_platform_charge_fallback`` with an
    append-only audit entry (who flipped it, before/after, why). Idempotent:
    setting the flag to its current value is a no-op that writes no audit."""

    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        audit: BillingAuditAppender | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._now = clock

    async def execute(self, cmd: SetPlatformChargeFallbackCommand) -> PlatformChargeFallbackResult:
        current = await self._settings.get()
        if current.allow_platform_charge_fallback == cmd.enabled:
            return PlatformChargeFallbackResult(allow_platform_charge_fallback=cmd.enabled)
        # Audit BEFORE the settings write: the charge-routing flag must never
        # change unaudited. If the upsert then fails, the entry records intent
        # for a change that didn't land, and the retry (flag still unchanged)
        # isn't swallowed by the no-op check above.
        if self._audit is not None:
            await self._audit.append(
                BillingAuditEntry(
                    audit_id=f"baud-{new_ulid()}",
                    academy_id=current.academy_id,
                    action="platform_fallback_toggled",
                    actor_id=cmd.actor_id,
                    at=self._now(),
                    reason=cmd.reason,
                    before={
                        "allow_platform_charge_fallback": current.allow_platform_charge_fallback
                    },
                    after={"allow_platform_charge_fallback": cmd.enabled},
                )
            )
        updated = current.model_copy(update={"allow_platform_charge_fallback": cmd.enabled})
        await self._settings.upsert(updated)
        return PlatformChargeFallbackResult(allow_platform_charge_fallback=cmd.enabled)


class SetInvoiceScheduleCommand(BaseModel):
    model_config = {"frozen": True}

    # Bounds mirror BillingSettings so an out-of-range value is rejected at the
    # command boundary rather than by the model deep inside the write.
    billing_day: int = Field(ge=1, le=28)
    invoice_due_days: int = Field(ge=0, le=60)
    actor_id: str
    reason: str | None = None


class InvoiceScheduleResult(BaseModel):
    model_config = {"frozen": True}

    billing_day: int
    invoice_due_days: int


class GetInvoiceScheduleSettings:
    def __init__(self, *, settings: BillingSettingsRepository) -> None:
        self._settings = settings

    async def execute(self) -> InvoiceScheduleResult:
        current = await self._settings.get()
        return InvoiceScheduleResult(
            billing_day=current.billing_day,
            invoice_due_days=current.invoice_due_days,
        )


class SetInvoiceScheduleSettings:
    """Set the automated-invoicing schedule with an append-only audit entry.

    ``billing_day`` decides when the daily generation job creates this
    academy's monthly invoices; ``invoice_due_days`` sets the due date, which
    is also when the dunning ladder makes its first autopay charge attempt.
    Both move real money timing, hence the audit. Idempotent: writing the
    current values is a no-op that writes no audit.
    """

    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        audit: BillingAuditAppender | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._now = clock

    async def execute(self, cmd: SetInvoiceScheduleCommand) -> InvoiceScheduleResult:
        current = await self._settings.get()
        if (
            current.billing_day == cmd.billing_day
            and current.invoice_due_days == cmd.invoice_due_days
        ):
            return InvoiceScheduleResult(
                billing_day=cmd.billing_day,
                invoice_due_days=cmd.invoice_due_days,
            )
        # Audit BEFORE the write, same rationale as SetPlatformChargeFallback:
        # the schedule must never change unaudited, and a failed upsert leaves
        # the values unchanged so the retry isn't swallowed by the no-op check.
        if self._audit is not None:
            await self._audit.append(
                BillingAuditEntry(
                    audit_id=f"baud-{new_ulid()}",
                    academy_id=current.academy_id,
                    action="invoice_schedule_changed",
                    actor_id=cmd.actor_id,
                    at=self._now(),
                    reason=cmd.reason,
                    before={
                        "billing_day": current.billing_day,
                        "invoice_due_days": current.invoice_due_days,
                    },
                    after={
                        "billing_day": cmd.billing_day,
                        "invoice_due_days": cmd.invoice_due_days,
                    },
                )
            )
        updated = current.model_copy(
            update={
                "billing_day": cmd.billing_day,
                "invoice_due_days": cmd.invoice_due_days,
            }
        )
        await self._settings.upsert(updated)
        return InvoiceScheduleResult(
            billing_day=cmd.billing_day,
            invoice_due_days=cmd.invoice_due_days,
        )
