"""Owner payroll settings (L7): validated at the API, audited, owner-only."""

from __future__ import annotations

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.payroll_settings import (
    GetPayrollSettings,
    UpdatePayrollSettings,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

URL = "/api/v2/admin/payroll-settings"
DEFAULTS = {
    "payroll_ach_discount_reduces_base": False,
    "payroll_count_checkout_first_month": True,
    "payroll_cancelled_class_share": "ran_only",
    "payroll_missing_invoices": "block",
    "payroll_assistant_pay_from": None,
}


class _Store:
    def __init__(self) -> None:
        self.settings = BillingSettings.default("acad").model_copy(
            update={"ach_discount_enabled": True}
        )

    async def get(self) -> BillingSettings:
        return self.settings

    async def set_payroll_settings(self, values: dict) -> None:
        self.settings = self.settings.model_copy(update=values)


class _Audit:
    def __init__(self) -> None:
        self.entries: list = []

    async def append(self, entry) -> None:
        self.entries.append(entry)


def _wire(client) -> tuple[_Store, _Audit]:
    store, audit = _Store(), _Audit()
    client.use_cases.get_payroll_settings = GetPayrollSettings(settings=store)
    client.use_cases.update_payroll_settings = UpdatePayrollSettings(
        settings=store, audit=RecordMoneySettingChange(audit=audit)
    )
    return store, audit


def test_owner_reads_defaults_and_saves_a_change_with_an_audit_entry(admin_client) -> None:
    store, audit = _wire(admin_client)

    assert admin_client.get(URL).json() == DEFAULTS

    changed = {**DEFAULTS, "payroll_missing_invoices": "pay_zero"}
    response = admin_client.put(URL, json=changed)

    assert response.status_code == 200, response.text
    assert response.json() == changed
    assert store.settings.payroll_missing_invoices == "pay_zero"
    assert store.settings.ach_discount_enabled is True  # other billing settings untouched
    [entry] = audit.entries
    assert entry.action == "payroll_settings_changed"
    assert entry.before["payroll_missing_invoices"] == "block"
    assert entry.after["payroll_missing_invoices"] == "pay_zero"

    # Saving the same values again writes no second audit entry.
    assert admin_client.put(URL, json=changed).status_code == 200
    assert len(audit.entries) == 1


def test_bad_values_and_unknown_fields_are_refused(admin_client) -> None:
    store, audit = _wire(admin_client)

    bad_literal = admin_client.put(URL, json={**DEFAULTS, "payroll_cancelled_class_share": "x"})
    extra = admin_client.put(URL, json={**DEFAULTS, "application_fee_bps": 900})
    missing = admin_client.put(URL, json={"payroll_missing_invoices": "pay_zero"})
    bad_month = admin_client.put(URL, json={**DEFAULTS, "payroll_assistant_pay_from": "2026-13"})

    assert [r.status_code for r in (bad_literal, extra, missing, bad_month)] == [422] * 4
    assert store.settings.application_fee_bps == 0
    assert audit.entries == []


def test_payroll_settings_are_owner_only(admin_only_client, coach_on_admin_client) -> None:
    # The owner gate refuses before any use case runs.
    for client in (admin_only_client, coach_on_admin_client):
        assert client.get(URL).status_code == 404
        assert client.put(URL, json=DEFAULTS).status_code == 404
