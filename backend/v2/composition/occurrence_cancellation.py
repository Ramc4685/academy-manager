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

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.v2.composition.payout_input_lock import compose_payout_input_lock
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
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    MongoClassFeeResolver,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.cancel_session_occurrence import (
    CancelSessionOccurrence,
)
from backend.v2.contexts.enrollment.application.use_cases.close_academy_dates import (
    CloseAcademyDates,
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
from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
    MongoSelfServicePolicyRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)

log = logging.getLogger(__name__)


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
        dry_run: bool = False,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            ApplyOccurrenceCancellationCommand(
                occurrence_id=occurrence_id,
                session_id=session_id,
                start_at=start_at,
                reason=reason[:500],
                actor_id=actor_id,
                dry_run=dry_run,
            )
        )
        return {
            "billing_policy": "cancelled_date_credited",
            "billing_result": result.billing_result,
            "period": result.period,
            "override_written": result.override_written,
            "schedule_matched": result.schedule_matched,
            "credits": result.credits,
            "credited_cents": result.credited_cents,
            "skip_counts": result.skip_counts,
            "families": [
                {
                    "enrollment_id": d.enrollment_id,
                    "amount_cents": d.amount_cents,
                    "outcome": d.outcome,
                }
                for d in result.decisions
            ],
        }


#: Marks that mean the student was there (``voided`` counts as unmarked, #554).
_PRESENT_STATUSES = frozenset({"present", "late"})


class OccurrenceAttendanceAdapter:
    """``OccurrenceAttendanceCheck`` over coaching's attendance rows (#1207)."""

    def __init__(self, attendance: MongoAttendanceRepository) -> None:
        self._attendance = attendance

    async def present_count(self, occurrence_id: str) -> int | None:
        """``None`` when attendance can't be read: the caller refuses then."""
        try:
            rows = await self._attendance.list_for_occurrence(occurrence_id)
        except Exception:
            log.warning(
                "missed_class_attendance_unreadable",
                extra={"occurrence_id": occurrence_id},
                exc_info=True,
            )
            return None
        return sum(1 for row in rows if row.status in _PRESENT_STATUSES)


def compose_apply_occurrence_cancellation(
    db: Any, *, clock: Callable[[], datetime] | None = None
) -> ApplyOccurrenceCancellation:
    """``clock`` pins "now" for tests: whether a month is past decides crediting."""
    return ApplyOccurrenceCancellation(
        clock=clock or (lambda: datetime.now(UTC)),
        reader=MongoOccurrenceCancellationReader(db),
        overrides=MongoOccurrenceOverrideRepository(db),
        invoices=MongoBillingLedgerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        # A credit priced from a month's class fee reads the plan price change
        # fence the way a registration quote does (Settings Phase 6 PR 26).
        price_fence=MongoClassFeeResolver(db),
    )


def compose_occurrence_billing_sync(db: Any) -> OccurrenceBillingSyncAdapter:
    return OccurrenceBillingSyncAdapter(compose_apply_occurrence_cancellation(db))


def compose_cancel_session_occurrence(
    db: Any, *, notifier: Any | None = None
) -> CancelSessionOccurrence:
    """The admin "cancel this date" use case, fully wired. main.py attaches the
    L9 guest notifier (``app.state.trial_emails``) after this runs."""
    return CancelSessionOccurrence(
        occurrences=MongoSessionOccurrenceRepository(db),
        sessions=MongoSessionRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        enrollment_events=MongoEnrollmentEventRepository(db),
        occurrence_roster=MongoOccurrenceRosterRepository(db),
        makeups=MongoMakeupRequestRepository(db),
        trials=MongoTrialRequestRepository(db),
        makeup_policies=MongoSelfServicePolicyRepository(db),
        billing_sync=compose_occurrence_billing_sync(db),
        notifier=notifier,
        # #787: refuse to call off a date whose payout is already frozen.
        payout_lock=compose_payout_input_lock(db),
        # #1207: a missed class is only credited when nobody was marked present.
        attendance=OccurrenceAttendanceAdapter(MongoAttendanceRepository(db)),
    )


def compose_occurrence_cancellations(
    db: Any, notifier: Any | None, materialize: Any
) -> dict[str, Any]:
    """Both admin cancel use cases. Academy closures loop over the SAME wired
    cancel instance (billing sync, payout lock, guest notifier shared) and send
    one summary per family through ``notifier.academy_closed``."""
    cancel = compose_cancel_session_occurrence(db, notifier=notifier)
    return {
        "cancel_session_occurrence": cancel,
        "close_academy_dates": CloseAcademyDates(
            cancel=cancel,
            occurrences=MongoSessionOccurrenceRepository(db),
            sessions=MongoSessionRepository(db),
            materialize=materialize,
            notifier=notifier,
        ),
    }
