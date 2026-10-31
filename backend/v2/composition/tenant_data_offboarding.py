"""Composition for platform tenant data export and purge dry-run (roadmap L9d).

Pure wiring for ``interfaces/platform/tenant_data_routes.py``: the route only
reads ``app.state.tenant_data_offboarding`` and never touches Mongo adapters.
Audit writes are not swallowed here: an export or dry-run that cannot be
audited must fail rather than run unrecorded.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.platform.application.use_cases.tenant_data_offboarding import (
    TenantDataOffboardingService,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    PlatformAuditService,
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.infrastructure.mongo_tenant_data_store import (
    MongoTenantDataStore,
)
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)


def compose_tenant_data_offboarding(
    db: Any, platform_audit: PlatformAuditService
) -> TenantDataOffboardingService:
    async def _record(command: RecordPlatformAuditEventCommand) -> object:
        return await platform_audit.record_event(command)

    return TenantDataOffboardingService(
        tenants=MongoTenantLifecycleRepository(db),
        data=MongoTenantDataStore(db),
        audit_recorder=_record,
    )
