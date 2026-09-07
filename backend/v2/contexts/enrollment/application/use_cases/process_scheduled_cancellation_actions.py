"""Process due scheduled ``cancel_at_period_end`` actions (issue #675).

A parent's ``end_of_period`` self-cancel (``SelfCancelEnrollment``) leaves the
enrollment ``active`` with ``pending_cancellation_at`` stamped and enqueues one
of these actions for that instant. This worker — run hourly by the
``process_scheduled_cancellation_actions`` scheduler job — performs the real
cancel once the month has ended: the status CAS (``cancelled_at`` = the
pending date, ``cancelled_by="parent"``), seat release, future one-time
occurrence roster cleanup, the ``"cancelled"`` lifecycle row, the
``EnrollmentCancelled`` outbox event that drives waitlist promotion, and the
staff alert. Mirrors ``ProcessScheduledResumeActions`` for the pause side.

Billing: ``SelfCancelEnrollment`` already applied the billing sync at request
time (the cancelled month stays payable, later invoices are voided, autopay is
disabled). It is applied AGAIN here with the same ``effective_at`` because the
rule is "every attendance-stopping transition calls billing_sync" and
``ApplyEnrollmentLifecycle`` is idempotent — an invoice voided in September is
skipped in October (its status is no longer voidable), and the autopay status
write is a no-op when already ``disabled``. A monthly invoice minted between
the request and the run (should not happen — the period is voided-on-mint by
status — but belt and braces) is caught by the second pass.

Outcomes per action:

- enrollment still active (or paused: an admin pause keeps the pending
  cancellation) → cancelled; ``succeeded``.
- enrollment already ended by an admin (cancel / withdraw / session cancel
  cleared the pending marker or flipped the status) → nothing to do;
  ``cancelled`` with the reason, never ``failed`` — an operator reading the
  blocked-actions list should not chase a cancellation that already happened.
- enrollment missing → ``failed`` (``enrollment_missing``).
- any other exception → ``failed`` with the error; the next hourly tick does
  NOT retry a failed row (same as the resume worker), so it lands on the
  admin's blocked-actions surface.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentEventRepository,
    OccurrenceRosterCleanup,
    RosterChangeNotifier,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    _billing_result,
    _drop_future_occurrence_roster,
    _notify_roster_change,
    _record_lifecycle_event,
    _sync_billing,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
    EnrollmentCancelledPayload,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.events import Outbox

log = logging.getLogger(__name__)


class PendingCancellationEnrollmentWriter(Protocol):
    async def get(self, enrollment_id: str) -> Enrollment | None: ...

    async def complete_pending_cancellation(
        self, enrollment_id: str, *, cancelled_at: datetime
    ) -> Enrollment | None:
        """CAS "still pending, not yet ended" -> cancelled. Returns the
        PRE-image (so the caller knows whether the row held a seat) or
        ``None`` when an admin ended the enrollment first."""


class PendingCancellationSessionWriter(Protocol):
    async def release_seat(self, session_id: str) -> None: ...


class ProcessScheduledCancellationActionsResult(BaseModel):
    model_config = {"frozen": True}

    processed: int = 0
    succeeded: int = 0
    skipped_already_ended: int = 0
    failed: int = 0


#: Statuses that still hold a seat; a paused row released its own when it
#: paused (see ``admin_writes.CancelEnrollment._SEATLESS_STATUSES``).
_SEATED_STATUSES = frozenset({"active"})


class ProcessScheduledCancellationActions:
    def __init__(
        self,
        *,
        scheduled_actions: ScheduledEnrollmentActionRepository,
        enrollments: PendingCancellationEnrollmentWriter,
        sessions: PendingCancellationSessionWriter,
        outbox: Outbox,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing_sync: EnrollmentBillingSync | None = None,
        occurrence_roster: OccurrenceRosterCleanup | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._scheduled_actions = scheduled_actions
        self._enrollments = enrollments
        self._sessions = sessions
        self._outbox = outbox
        self._enrollment_events = enrollment_events
        self._billing_sync = billing_sync
        self._occurrence_roster = occurrence_roster
        self._roster_notifier = roster_notifier
        self._now = clock

    async def execute(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> ProcessScheduledCancellationActionsResult:
        attempted_at = now or self._now()
        actions = [
            a
            for a in await self._scheduled_actions.list_due(now=attempted_at, limit=limit)
            if a.action_type == "cancel_at_period_end"
        ]
        succeeded = skipped = failed = 0
        for action in actions:
            try:
                outcome = await self._run_one(action, attempted_at=attempted_at)
            except Exception as exc:
                log.exception(
                    "scheduled_cancellation_failed",
                    extra={"action_id": action.action_id, "enrollment_id": action.enrollment_id},
                )
                await self._scheduled_actions.mark_failed(
                    action.action_id, attempted_at=attempted_at, error=str(exc)[:500]
                )
                failed += 1
                continue
            if outcome == "succeeded":
                succeeded += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
        return ProcessScheduledCancellationActionsResult(
            processed=len(actions),
            succeeded=succeeded,
            skipped_already_ended=skipped,
            failed=failed,
        )

    async def _run_one(self, action: ScheduledEnrollmentAction, *, attempted_at: datetime) -> str:
        enrollment = await self._enrollments.get(action.enrollment_id)
        if enrollment is None:
            await self._scheduled_actions.mark_failed(
                action.action_id, attempted_at=attempted_at, error="enrollment_missing"
            )
            return "failed"
        cancelled_at = enrollment.pending_cancellation_at or action.run_at
        before = await self._enrollments.complete_pending_cancellation(
            action.enrollment_id, cancelled_at=cancelled_at
        )
        if before is None:
            # An admin cancel / withdraw / session cancel got there first and
            # already released the seat, synced billing and wrote its own row.
            await self._scheduled_actions.mark_cancelled(
                action.action_id,
                attempted_at=attempted_at,
                reason=f"enrollment_already_ended:{enrollment.status}",
            )
            return "skipped"

        # From here the flip is committed; everything below mirrors
        # ``admin_writes.CancelEnrollment`` in order. The seat comes first
        # because nothing later re-derives ``reserved_seats``.
        if before.status in _SEATED_STATUSES:
            await self._sessions.release_seat(before.session_id)
        await _drop_future_occurrence_roster(
            self._occurrence_roster,
            session_id=before.session_id,
            student_id=before.student_id,
            after=cancelled_at,
        )
        billing = await _sync_billing(
            self._billing_sync,
            enrollment_id=before.enrollment_id,
            transition="cancelled",
            effective_at=cancelled_at,
            reason=before.cancellation_reason or "parent_cancel",
            actor_id="system",
        )
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=before.academy_id,
            event_type="cancelled",
            enrollment_id=before.enrollment_id,
            session_id=before.session_id,
            student_id=before.student_id,
            actor_id="system",
            reason=before.cancellation_reason or "parent_cancel",
            effective_at=cancelled_at,
            occurred_at=attempted_at,
            billing_policy="current_period_payable_future_voided",
            billing_result=_billing_result(billing),
        )
        await self._outbox.append(
            EnrollmentCancelled(
                aggregate_id=before.enrollment_id,
                academy_id=before.academy_id,
                payload=EnrollmentCancelledPayload(
                    enrollment_id=before.enrollment_id,
                    session_id=before.session_id,
                    student_id=before.student_id,
                    reason="parent_cancel",
                ),
            )
        )
        await _notify_roster_change(
            self._roster_notifier,
            change="cancelled",
            session_id=before.session_id,
            student_id=before.student_id,
            enrollment_id=before.enrollment_id,
            actor_id="system",
        )
        await self._scheduled_actions.mark_succeeded(action.action_id, attempted_at=attempted_at)
        return "succeeded"


__all__ = [
    "PendingCancellationEnrollmentWriter",
    "PendingCancellationSessionWriter",
    "ProcessScheduledCancellationActions",
    "ProcessScheduledCancellationActionsResult",
]
