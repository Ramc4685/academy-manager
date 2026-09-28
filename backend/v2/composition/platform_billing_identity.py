"""Composition for the per-academy invoice prefix (Settings overhaul Phase 1 PR 2).

Pure wiring for ``interfaces/platform/billing_identity_routes.py`` and for the
two academy-creation paths (``BootstrapAcademy`` and
``TenantLifecycleService.create_tenant``), which call
``AssignInvoicePrefix`` through their own ports. The billing-settings and
audit repositories are tenant-scoped and resolve the academy at execution
time: the use cases enter ``tenant_scope(academy_id)`` with the academy named
in the platform route's path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.invoice_prefix import (
    AssignInvoicePrefix,
    GetInvoicePrefix,
    SetInvoicePrefix,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)


@dataclass(frozen=True)
class PlatformBillingIdentity:
    """What the platform billing-identity routes read off app.state."""

    get: GetInvoicePrefix
    set: SetInvoicePrefix


def compose_invoice_prefix_assigner(db: Any) -> AssignInvoicePrefix:
    return AssignInvoicePrefix(settings=MongoBillingSettingsRepository(db))


def compose_platform_billing_identity(db: Any) -> PlatformBillingIdentity:
    async def academy_exists(academy_id: str) -> bool:
        # A plain existence probe, as for the application fee: legacy academy
        # docs that do not parse as a platform Tenant still take payments.
        count: int = await db["academies"].count_documents({"academy_id": academy_id}, limit=1)
        return count > 0

    async def has_numbered_invoice(academy_id: str) -> bool:
        # Served by the partial (academy_id, invoice_number) unique index.
        count: int = await db["invoices"].count_documents(
            {"academy_id": academy_id, "invoice_number": {"$gt": ""}}, limit=1
        )
        return count > 0

    async def prefix_taken(prefix: str, academy_id: str) -> bool:
        # Deliberately cross-academy: prefixes are unique platform-wide.
        count: int = await db["billing_settings"].count_documents(
            {"invoice_number_prefix": prefix, "academy_id": {"$ne": academy_id}}, limit=1
        )
        return count > 0

    settings = MongoBillingSettingsRepository(db)
    return PlatformBillingIdentity(
        get=GetInvoicePrefix(
            settings=settings,
            academy_exists=academy_exists,
            has_numbered_invoice=has_numbered_invoice,
        ),
        set=SetInvoicePrefix(
            settings=settings,
            audit=MongoBillingAuditLogRepository(db),
            academy_exists=academy_exists,
            has_numbered_invoice=has_numbered_invoice,
            prefix_taken=prefix_taken,
        ),
    )
