"""Composition for "Not billed" / "Start billing" on one enrollment.

Outside ``composition/admin.py``, which sits at its line budget. Reuses the
admin composition's ``void_billing_invoice`` (refuses money-bearing invoices,
unwinds credit and the Stripe twin, audits) for the optional void. Every repo
resolves the tenant at execution time.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.enrollment_not_billed import (
    SetEnrollmentBilling,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_enrollment_not_billed_store import (
    MongoEnrollmentNotBilledStore,
)
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    MongoAcademyBillingMonth,
)


def compose_admin_enrollment_billing(db: Any, admin: Any) -> SetEnrollmentBilling:
    return SetEnrollmentBilling(
        store=MongoEnrollmentNotBilledStore(db),
        invoices=MongoBillingLedgerRepository(db),
        void_invoice=admin.void_billing_invoice,
        billing_month=MongoAcademyBillingMonth(db),
        audit=RecordMoneySettingChange(audit=MongoBillingAuditLogRepository(db)),
    )
