"""Composition for the admin Family billing page (``/admin/families/{parent_id}/…``).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.

ONE DELIBERATE EXCEPTION (#778): ``MongoSuppressionRepository`` is not
tenant-scoped, by design — the Resend sender domain is shared, so a hard
bounce observed under any academy stops every academy mailing that mailbox.
It is read here keyed by an address this admin's own page already displays,
and the only fact it yields is "we cannot reach this address", which is true
for this tenant too. No other tenant's data is reachable through it.
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
from backend.v2.contexts.communications.infrastructure.mongo_suppression_repo import (
    MongoSuppressionRepository,
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
        # #778: the suppression list is deliberately NOT tenant-scoped (the
        # Resend sender domain is shared), so a bounce seen anywhere stops
        # this academy mailing the same address — and this page must say so.
        suppressions=MongoSuppressionRepository(db),
    )
    pause = PauseFamilyAutopay(
        enrollments=MongoStudentBillingEnrollmentRepository(db),
        audit=audit,
        idempotency=MongoIdempotencyStore(db),
    )
    return AdminFamilies(reader=reader, pause_autopay=pause)
