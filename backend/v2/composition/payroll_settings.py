"""Composition for the coach payroll settings card (L7).

Kept out of ``composition/admin.py`` for its line budget; attached onto the
built ``AdminUseCases`` in ``main.py`` like ``composition/departures.py``.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.payroll_settings import (
    GetPayrollSettings,
    UpdatePayrollSettings,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)


def compose_payroll_settings(db: Any) -> tuple[GetPayrollSettings, UpdatePayrollSettings]:
    settings = MongoBillingSettingsRepository(db)
    audit = RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db))
    return GetPayrollSettings(settings=settings), UpdatePayrollSettings(
        settings=settings, audit=audit
    )
