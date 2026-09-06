"""Composition for the admin Family billing page (``/admin/families/{parent_id}/…``).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


@dataclass(frozen=True)
class AdminFamilies:
    reader: MongoFamilyBillingReadModel
    pause_autopay: PauseFamilyAutopay


def compose_admin_families(db: Any) -> AdminFamilies:
    audit = MongoBillingAuditLogRepository(db)
    reader = MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=audit,
    )
    pause = PauseFamilyAutopay(
        enrollments=MongoStudentBillingEnrollmentRepository(db),
        audit=audit,
        idempotency=MongoIdempotencyStore(db),
    )
    return AdminFamilies(reader=reader, pause_autopay=pause)
