"""Wire "cancel one class date" end to end (issue #671).

Sibling of ``composition/lifecycle_billing.py``. The enrollment context owns
the write (``CancelSessionOccurrence``); billing owns the money
(``ApplyOccurrenceCancellation``); neither may import the other, so the
adapter over the ``OccurrenceBillingSync`` port lives here.

INVARIANT: every composition root that builds ``CancelSessionOccurrence``
MUST pass the billing sync from ``compose_occurrence_billing_sync``. Without
it a cancelled date still bills the family in full — the use case logs
``occurrence_billing_sync_unwired`` and carries on, because a class that is
cancelled must stay cancelled even if billing cannot be reached.

Kept out of ``composition/admin.py``: that module is at its hard 4800-line
structural cap, so admin wires this feature in one call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.apply_occurrence_cancellation import (
    ApplyOccurrenceCancellation,
    ApplyOccurrenceCancellationCommand,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_occurrence_cancellation import (
    MongoOccurrenceCancellationReader,
    MongoOccurrenceOverrideRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
    MongoMakeupRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)


class OccurrenceBillingSyncAdapter:
    """``OccurrenceBillingSync`` implementation backed by the billing use case."""

    def __init__(self, use_case: ApplyOccurrenceCancellation) -> None:
        self._use_case = use_case

    async def apply(
        self,
        *,
        occurrence_id: str,
        session_id: str,
        start_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            ApplyOccurrenceCancellationCommand(
                occurrence_id=occurrence_id,
                session_id=session_id,
                start_at=start_at,
                reason=reason[:500],
                actor_id=actor_id,
            )
        )
        return {
            "billing_policy": "cancelled_date_credited",
            "billing_result": result.billing_result,
            "period": result.period,
            "override_written": result.override_written,
            "credits": result.credits,
        }


def compose_apply_occurrence_cancellation(db: Any) -> ApplyOccurrenceCancellation:
    return ApplyOccurrenceCancellation(
        reader=MongoOccurrenceCancellationReader(db),
        overrides=MongoOccurrenceOverrideRepository(db),
        invoices=MongoBillingLedgerRepository(db),
        credits=MongoCreditLedgerRepository(db),
    )


def compose_occurrence_billing_sync(db: Any) -> OccurrenceBillingSyncAdapter:
    return OccurrenceBillingSyncAdapter(compose_apply_occurrence_cancellation(db))


def compose_cancel_session_occurrence(
    db: Any, *, notifier: Any | None = None
) -> CancelSessionOccurrence:
    """The admin "cancel this date" use case, fully wired."""
    return CancelSessionOccurrence(
        occurrences=MongoSessionOccurrenceRepository(db),
        sessions=MongoSessionRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        enrollment_events=MongoEnrollmentEventRepository(db),
        occurrence_roster=MongoOccurrenceRosterRepository(db),
        makeups=MongoMakeupRequestRepository(db),
        billing_sync=compose_occurrence_billing_sync(db),
        notifier=notifier,
    )
