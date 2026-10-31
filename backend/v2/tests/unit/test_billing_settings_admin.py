"""Platform-charge (read-only) and invoice-schedule billing settings use cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    GetInvoiceScheduleSettings,
    GetPlatformChargeFallback,
    SetInvoiceScheduleCommand,
    SetInvoiceScheduleSettings,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

NOW = datetime(2026, 7, 5, tzinfo=UTC)


class _SettingsRepo:
    def __init__(self, settings: BillingSettings) -> None:
        self._settings = settings
        self.upserts: list[BillingSettings] = []

    async def get(self) -> BillingSettings:
        return self._settings

    async def upsert(self, settings: BillingSettings) -> None:
        self._settings = settings
        self.upserts.append(settings)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[BillingAuditEntry] = []

    async def append(self, entry: BillingAuditEntry) -> None:
        self.entries.append(entry)


@pytest.mark.asyncio
async def test_get_returns_current_flag() -> None:
    repo = _SettingsRepo(
        BillingSettings.default("acad-1").model_copy(
            update={"allow_platform_charge_fallback": True}
        )
    )

    result = await GetPlatformChargeFallback(settings=repo).execute()

    assert result.allow_platform_charge_fallback is True


# --- invoice schedule (issue #288) ---------------------------------------


@pytest.mark.asyncio
async def test_invoice_schedule_defaults_to_the_first_with_a_week_of_grace() -> None:
    """The defaults are the contract the scheduler job relies on: an academy
    that never touches this setting still generates on the 1st."""
    result = await GetInvoiceScheduleSettings(
        settings=_SettingsRepo(BillingSettings.default("acad-1"))
    ).execute()

    assert result.billing_day == 1
    assert result.invoice_due_days == 7


@pytest.mark.asyncio
async def test_set_invoice_schedule_writes_settings_and_audit_trail() -> None:
    repo = _SettingsRepo(BillingSettings.default("acad-1"))
    audit = _Audit()
    uc = SetInvoiceScheduleSettings(settings=repo, audit=audit, clock=lambda: NOW)

    result = await uc.execute(
        SetInvoiceScheduleCommand(
            billing_day=5,
            invoice_due_days=10,
            actor_id="admin-1",
            reason="align with payroll",
        )
    )

    assert (result.billing_day, result.invoice_due_days) == (5, 10)
    assert [(s.billing_day, s.invoice_due_days) for s in repo.upserts] == [(5, 10)]
    entry = audit.entries[0]
    assert entry.action == "invoice_schedule_changed"
    assert entry.actor_id == "admin-1"
    assert entry.reason == "align with payroll"
    assert entry.before == {
        "billing_day": 1,
        "invoice_due_days": 7,
        # Issue #774: the reminder offsets travel with the schedule audit.
        "reminder_days": [15, 20],
    }
    assert entry.after == {
        "billing_day": 5,
        "invoice_due_days": 10,
        "reminder_days": [15, 20],
    }
    assert entry.at == NOW


@pytest.mark.asyncio
async def test_set_invoice_schedule_to_current_values_is_a_noop_without_audit() -> None:
    repo = _SettingsRepo(BillingSettings.default("acad-1"))
    audit = _Audit()
    uc = SetInvoiceScheduleSettings(settings=repo, audit=audit, clock=lambda: NOW)

    await uc.execute(
        SetInvoiceScheduleCommand(billing_day=1, invoice_due_days=7, actor_id="admin-1")
    )

    assert repo.upserts == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_set_invoice_schedule_audit_failure_blocks_settings_write() -> None:
    """Audit-first ordering: the schedule
    decides when parents get charged, so it must never move unaudited."""

    class _FailingAudit:
        async def append(self, entry: BillingAuditEntry) -> None:
            raise RuntimeError("audit log unavailable")

    repo = _SettingsRepo(BillingSettings.default("acad-1"))
    uc = SetInvoiceScheduleSettings(settings=repo, audit=_FailingAudit(), clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="audit log unavailable"):
        await uc.execute(
            SetInvoiceScheduleCommand(billing_day=5, invoice_due_days=10, actor_id="admin-1")
        )

    assert repo.upserts == []
    assert (await repo.get()).billing_day == 1


@pytest.mark.asyncio
async def test_set_invoice_schedule_preserves_other_settings() -> None:
    repo = _SettingsRepo(
        BillingSettings.default("acad-1").model_copy(
            update={"allow_platform_charge_fallback": True, "ach_discount_enabled": True}
        )
    )
    uc = SetInvoiceScheduleSettings(settings=repo, clock=lambda: NOW)

    await uc.execute(
        SetInvoiceScheduleCommand(billing_day=28, invoice_due_days=0, actor_id="admin-1")
    )

    written = repo.upserts[-1]
    assert written.allow_platform_charge_fallback is True
    assert written.ach_discount_enabled is True
    assert (written.billing_day, written.invoice_due_days) == (28, 0)


@pytest.mark.parametrize("billing_day", [0, 29, 31])
def test_billing_day_outside_1_to_28_is_rejected(billing_day: int) -> None:
    """29-31 are rejected rather than clamped: an academy that asked for the
    31st would silently skip February, and a skipped month is only recoverable
    by an admin noticing it."""
    with pytest.raises(ValidationError):
        SetInvoiceScheduleCommand(billing_day=billing_day, invoice_due_days=7, actor_id="admin-1")


@pytest.mark.parametrize("invoice_due_days", [-1, 61])
def test_invoice_due_days_outside_0_to_60_is_rejected(invoice_due_days: int) -> None:
    with pytest.raises(ValidationError):
        SetInvoiceScheduleCommand(
            billing_day=1, invoice_due_days=invoice_due_days, actor_id="admin-1"
        )
