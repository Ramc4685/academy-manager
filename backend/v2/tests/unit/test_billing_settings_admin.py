"""SetPlatformChargeFallback / GetPlatformChargeFallback use cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    GetPlatformChargeFallback,
    SetPlatformChargeFallback,
    SetPlatformChargeFallbackCommand,
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
async def test_enable_writes_settings_and_audit_trail() -> None:
    repo = _SettingsRepo(BillingSettings.default("acad-1"))
    audit = _Audit()
    uc = SetPlatformChargeFallback(settings=repo, audit=audit, clock=lambda: NOW)

    result = await uc.execute(
        SetPlatformChargeFallbackCommand(
            enabled=True, actor_id="admin-1", reason="connect under review"
        )
    )

    assert result.allow_platform_charge_fallback is True
    assert [s.allow_platform_charge_fallback for s in repo.upserts] == [True]
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "platform_fallback_toggled"
    assert entry.actor_id == "admin-1"
    assert entry.reason == "connect under review"
    assert entry.before == {"allow_platform_charge_fallback": False}
    assert entry.after == {"allow_platform_charge_fallback": True}
    assert entry.at == NOW


@pytest.mark.asyncio
async def test_disable_after_enable_round_trips() -> None:
    repo = _SettingsRepo(
        BillingSettings.default("acad-1").model_copy(
            update={"allow_platform_charge_fallback": True}
        )
    )
    audit = _Audit()
    uc = SetPlatformChargeFallback(settings=repo, audit=audit, clock=lambda: NOW)

    result = await uc.execute(SetPlatformChargeFallbackCommand(enabled=False, actor_id="admin-1"))

    assert result.allow_platform_charge_fallback is False
    assert repo.upserts[-1].allow_platform_charge_fallback is False
    assert audit.entries[0].before == {"allow_platform_charge_fallback": True}


@pytest.mark.asyncio
async def test_setting_current_value_is_a_noop_without_audit() -> None:
    repo = _SettingsRepo(BillingSettings.default("acad-1"))
    audit = _Audit()
    uc = SetPlatformChargeFallback(settings=repo, audit=audit, clock=lambda: NOW)

    result = await uc.execute(SetPlatformChargeFallbackCommand(enabled=False, actor_id="admin-1"))

    assert result.allow_platform_charge_fallback is False
    assert repo.upserts == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_toggle_preserves_other_settings() -> None:
    repo = _SettingsRepo(
        BillingSettings.default("acad-1").model_copy(
            update={"ach_discount_enabled": True, "ach_discount_percent": 2.0}
        )
    )
    uc = SetPlatformChargeFallback(settings=repo, clock=lambda: NOW)

    await uc.execute(SetPlatformChargeFallbackCommand(enabled=True, actor_id="admin-1"))

    written = repo.upserts[-1]
    assert written.ach_discount_enabled is True
    assert written.ach_discount_percent == 2.0
    assert written.allow_platform_charge_fallback is True


@pytest.mark.asyncio
async def test_get_returns_current_flag() -> None:
    repo = _SettingsRepo(
        BillingSettings.default("acad-1").model_copy(
            update={"allow_platform_charge_fallback": True}
        )
    )

    result = await GetPlatformChargeFallback(settings=repo).execute()

    assert result.allow_platform_charge_fallback is True
