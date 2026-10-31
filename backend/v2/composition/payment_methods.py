"""Composition for Settings -> Billing rules -> Offline payments.

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: identity owns the stored list on the academy record,
billing owns the owner-only audited write around it. Nothing tenant-specific
is captured here: every call takes ``academy_id`` from the request claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.manual_payment_methods import (
    UpdateManualPaymentMethods,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.identity.application.academy_payment_methods import (
    GetAcademyPaymentMethods,
    SetAcademyPaymentMethods,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository


@dataclass(frozen=True)
class AdminPaymentMethods:
    """What ``interfaces/admin/payment_methods_routes.py`` reads off app.state."""

    read: GetAcademyPaymentMethods
    write: UpdateManualPaymentMethods


def compose_admin_payment_methods(db: Any) -> AdminPaymentMethods:
    academies = MongoAcademyRepository(db)
    read = GetAcademyPaymentMethods(academies)
    return AdminPaymentMethods(
        read=read,
        write=UpdateManualPaymentMethods(
            reader=read,
            writer=SetAcademyPaymentMethods(academies),
            audit=MongoBillingAuditLogRepository(db),
        ),
    )
