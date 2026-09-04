"""Wire enrollment lifecycle transitions into billing (issue #651).

Adapts the enrollment context's ``EnrollmentBillingSync`` port onto the
billing context's ``ApplyEnrollmentLifecycle`` use case. Built once per
composition root and injected into every enrollment use case that stops or
resumes attendance.

INVARIANT: every composition root that builds cancel / withdraw / pause /
resume / session-cancel / self-cancel use cases MUST pass the adapter from
``compose_enrollment_billing_sync``. Leaving it out silently re-opens the
"cancelled family keeps getting auto-charged" defect; the use cases log an
error when the port is missing, but nothing else stops the charge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_lifecycle import (
    ApplyEnrollmentLifecycle,
    ApplyEnrollmentLifecycleCommand,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


class EnrollmentBillingSyncAdapter:
    """``EnrollmentBillingSync`` implementation backed by the billing use case."""

    def __init__(self, use_case: ApplyEnrollmentLifecycle) -> None:
        self._use_case = use_case

    async def apply(
        self,
        *,
        enrollment_id: str,
        transition: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            ApplyEnrollmentLifecycleCommand(
                enrollment_id=enrollment_id,
                transition=transition,  # type: ignore[arg-type]
                effective_at=effective_at,
                reason=reason[:500],
                actor_id=actor_id,
            )
        )
        return {
            "billing_policy": "current_period_payable_future_voided",
            "billing_result": result.billing_result,
            "voided_invoice_ids": list(result.voided_invoice_ids),
            "retained_invoice_ids": list(result.retained_invoice_ids),
            "autopay_status": result.autopay_status,
            "autopay_applied": result.autopay_applied,
            "ladders_suppressed": result.ladders_suppressed,
        }


def compose_enrollment_billing_sync(
    db: Any,
    *,
    ledger: MongoBillingLedgerRepository | None = None,
    autopay: MongoStudentBillingEnrollmentRepository | None = None,
    dunning: MongoDunningStateRepository | None = None,
) -> EnrollmentBillingSyncAdapter:
    """Build the adapter. Repos may be shared with the caller's own instances."""
    timezone_lookup = academy_timezone_lookup(db)

    async def request_academy_timezone() -> str | None:
        # Resolved at execution time from the request's tenant — never capture
        # an academy id at composition time (see AGENTS.md tenancy rule).
        return await timezone_lookup(current_academy_id())

    use_case = ApplyEnrollmentLifecycle(
        ledger=ledger or MongoBillingLedgerRepository(db),
        autopay=autopay or MongoStudentBillingEnrollmentRepository(db),
        dunning=dunning or MongoDunningStateRepository(db),
        academy_timezone=request_academy_timezone,
    )
    return EnrollmentBillingSyncAdapter(use_case)
