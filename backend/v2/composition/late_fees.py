"""Composition for the automated late-fee pass (issue #552).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at call time, so nothing tenant-specific is captured
here and one instance serves every academy the scheduler walks.

Wired on ``app.state`` and driven from the dunning scheduler tick in
``main.py`` — the same job that already retries autopay and sends the notice
that will now quote the higher balance.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import AddInvoiceLine
from backend.v2.contexts.billing.application.use_cases.apply_late_fees import ApplyLateFees
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.identity.application.get_academy_fees_use_case import (
    GetAcademyFeesUseCase,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


def compose_apply_late_fees(db: Any) -> ApplyLateFees:
    ledger = MongoBillingLedgerRepository(db)
    return ApplyLateFees(
        ledger=ledger,
        # No counters/settings: this path only ever appends to an invoice that
        # already exists (Mode A), so nothing here mints an invoice number.
        add_line=AddInvoiceLine(ledger=ledger),
        fees=GetAcademyFeesUseCase(MongoAcademyRepository(db)),
        dunning=MongoDunningStateRepository(db),
        audit=MongoBillingAuditLogRepository(db),
        # Takes the academy id the scheduler passes in; nothing is captured.
        academy_timezone=academy_timezone_lookup(db),
    )
