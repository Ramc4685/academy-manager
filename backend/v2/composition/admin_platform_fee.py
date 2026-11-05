"""Composition for the academy admin's read-only processing-fee view
(``GET /admin/billing/platform-fee``, AI strategy Phase 2 slice A1).

Lives outside ``composition/admin.py`` because that module sits at its line
budget. Pure wiring: the settings repository is tenant-scoped and resolves the
academy from ``current_academy_id()`` at request time.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    ReadAcademyApplicationFee,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)


def compose_admin_platform_fee(db: Any) -> ReadAcademyApplicationFee:
    return ReadAcademyApplicationFee(settings=MongoBillingSettingsRepository(db))
