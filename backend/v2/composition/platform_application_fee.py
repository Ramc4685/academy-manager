"""Composition for the platform-admin application-fee setting (roadmap L9b).

Pure wiring for ``interfaces/platform/application_fee_routes.py``. The
billing-settings and audit repositories are tenant-scoped and resolve the
academy at execution time: the use cases enter ``tenant_scope(academy_id)``
with the academy named in the platform route's path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    GetApplicationFee,
    SetApplicationFee,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)


@dataclass(frozen=True)
class PlatformApplicationFee:
    """What the platform application-fee routes read off app.state."""

    get: GetApplicationFee
    set: SetApplicationFee


def compose_platform_application_fee(db: Any) -> PlatformApplicationFee:
    academies = db["academies"]

    async def academy_exists(academy_id: str) -> bool:
        # A plain existence probe, not TenantLifecycle.get_by_id: legacy
        # academy docs that do not parse as a platform Tenant still exist and
        # still take payments, so they must still be configurable.
        count: int = await academies.count_documents({"academy_id": academy_id}, limit=1)
        return count > 0

    settings = MongoBillingSettingsRepository(db)
    return PlatformApplicationFee(
        get=GetApplicationFee(settings=settings, academy_exists=academy_exists),
        set=SetApplicationFee(
            settings=settings,
            audit=MongoBillingAuditLogRepository(db),
            academy_exists=academy_exists,
        ),
    )
