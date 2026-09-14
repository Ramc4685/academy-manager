"""Admin "drop at end of period" (issue #820, follow-up to #742).

The academy's departure policy has a value — ``no_credit_end_of_period`` —
whose timing half was honoured nowhere: the Drop dialog mapped it to the money
outcome ``adjustment`` and then called ``WithdrawEnrollment``, which flips the
status, releases the seat and closes every dependent in the SAME call
regardless of ``effective_at``. A future date was metadata, not a deferral, so
the child lost their place the day the admin clicked Drop.

This module is the missing half, built on the #675 scheduled-action machinery
rather than beside it:

``ScheduleAdminDropAtPeriodEnd``
    Stamps ``pending_cancellation_at`` (the marker every roster / profile /
    coach surface already renders as "ends <date>") and enqueues an
    ``admin_drop_at_period_end`` action for that instant. The row stays live
    and seated; the family keeps the month they paid for.

``ProcessScheduledAdminDropActions``
    The month-end worker. It does NOT re-implement the drop: it replays
    ``WithdrawEnrollment`` with the outcome, reason, reason code and ACTOR
    frozen at request time, so the money decision, the seat release, the
    billing sync, the ``dropped`` lifecycle row and the #743 family notice are
    byte-for-byte what an immediate Drop would have produced — just a month
    later. This is why it is a distinct action type from the parent's
    ``cancel_at_period_end``, whose worker records a ``cancelled`` row with
    parent semantics.

``CancelScheduledAdminDrop``
    An admin changed their mind (or the family re-signed). Clears the marker
    and retires the queued action. Deliberately no money side: nothing was
    charged, credited or refunded at request time — the whole decision was
    deferred with the drop.

WORKER CONTRACT (issue #675): the three action types share one collection and
a worker that takes another type's row no-ops it and retires it, losing the
work for good. ``list_due`` is therefore always called with this worker's own
``action_type``, and the result is filtered again in Python.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    RosterChangeNotifier,
    WithdrawalOutcome,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    WithdrawEnrollmentCommand,
    _record_lifecycle_event,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.departure_policy import DepartureReasonCode
from backend.v2.contexts.enrollment.domain.errors import (
    EnrollmentNotFound,
    EnrollmentNotWithdrawable,
)
from backend.v2.contexts.enrollment.domain.models import LIVE, Enrollment
from backend.v2.contexts.enrollment.domain.scheduling import end_of_academy_month
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]
AcademyTimezoneReader = Callable[[], Awaitable[str | None]]

ACTION_TYPE = "admin_drop_at_period_end"

#: How many times a transient failure is retried before the row is parked as
#: ``failed`` for a human — same budget and rationale as the parent worker
#: (``process_scheduled_cancellation_actions.MAX_ATTEMPTS``).
MAX_ATTEMPTS = 3


class PeriodEndDropEnrollmentWriter(Protocol):
    async def get(self, enrollment_id: str) -> Enrollment | None: ...

    async def mark_pending_cancellation_by_admin(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        pending_cancellation_at: datetime,
        requested_at: datetime,
    ) -> Enrollment | None: ...

    async def clear_pending_cancellation(self, enrollment_id: str) -> Enrollment | None: ...


class WithdrawEnrollmentExecutor(Protocol):
    """The subset of ``WithdrawEnrollment`` this worker drives. A Protocol,
    not the class, so the worker can be unit-tested without standing up the
    whole withdrawal (billing decision port, outbox, seat writer…)."""

    async def execute(self, cmd: WithdrawEnrollmentCommand) -> None: ...


class ScheduleAdminDropAtPeriodEndCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    outcome: WithdrawalOutcome = "adjustment"
    actor_id: str
    reason: str = Field(min_length=1)
    reason_code: DepartureReasonCode | None = None


class ScheduleAdminDropAtPeriodEndResult(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    pending_cancellation_at: datetime


class ScheduleAdminDropAtPeriodEnd:
    def __init__(
        self,
        *,
        enrollments: PeriodEndDropEnrollmentWriter,
        scheduled_actions: ScheduledEnrollmentActionRepository,
        enrollment_events: EnrollmentEventRepository | None = None,
        roster_notifier: RosterChangeNotifier | None = None,
        academy_timezone: AcademyTimezoneReader | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._scheduled_actions = scheduled_actions
        self._enrollment_events = enrollment_events
        self._roster_notifier = roster_notifier
        self._academy_timezone = academy_timezone
        self._now = clock

    async def execute(
        self, cmd: ScheduleAdminDropAtPeriodEndCommand
    ) -> ScheduleAdminDropAtPeriodEndResult:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if enrollment.status not in LIVE:
            raise EnrollmentNotWithdrawable(
                f"Enrollment is already {enrollment.status}; it cannot be dropped again.",
                enrollment_id=enrollment.enrollment_id,
                status=enrollment.status,
            )
        now = self._now()
        run_at = end_of_academy_month(now, await self._timezone())
        updated = await self._enrollments.mark_pending_cancellation_by_admin(
            cmd.enrollment_id,
            cancellation_reason=cmd.reason,
            pending_cancellation_at=run_at,
            requested_at=now,
        )
        if updated is None:
            # Either a departure already landed between the read and the CAS,
            # or this row already has a pending cancellation (the parent's or
            # another admin's). Never enqueue a second one: two actions would
            # both fire and the loser would log a dishonest failure.
            raise EnrollmentNotWithdrawable(
                "This enrollment is already scheduled to end, or has already ended.",
                enrollment_id=enrollment.enrollment_id,
                status=enrollment.status,
            )
        # Load-bearing and NOT swallowed: a marker with no action behind it
        # leaves the child attending forever while every surface says they
        # left. The repo upserts on (enrollment, type, pending), so a retry
        # after a transient failure converges rather than double-booking.
        await self._scheduled_actions.add(
            ScheduledEnrollmentAction(
                action_id=str(new_ulid()),
                academy_id=enrollment.academy_id,
                action_type=ACTION_TYPE,
                enrollment_id=enrollment.enrollment_id,
                pause_request_id=None,
                run_at=run_at,
                outcome=cmd.outcome,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
                reason_code=cmd.reason_code,
                created_at=now,
                updated_at=now,
            )
        )
        await self._record_scheduled(enrollment, cmd=cmd, run_at=run_at, now=now)
        return ScheduleAdminDropAtPeriodEndResult(
            enrollment_id=enrollment.enrollment_id, pending_cancellation_at=run_at
        )

    async def _timezone(self) -> str | None:
        if self._academy_timezone is None:
            return None
        try:
            return await self._academy_timezone()
        except Exception:
            log.warning("admin_period_end_drop_timezone_lookup_failed")
            return None

    async def _record_scheduled(
        self,
        enrollment: Enrollment,
        *,
        cmd: ScheduleAdminDropAtPeriodEndCommand,
        run_at: datetime,
        now: datetime,
    ) -> None:
        """Timeline row + coach alert. Both cosmetic, both swallowed — the
        schedule is already committed and must not be undone by a mail blip.

        The alert is ``cancellation_scheduled``, never ``withdrawn``: the
        child is still on the roster until month end, and the real drop
        notice (including the #743 family email) fires when
        ``WithdrawEnrollment`` runs.
        """
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=enrollment.academy_id,
            event_type="cancellation_scheduled",
            enrollment_id=enrollment.enrollment_id,
            session_id=enrollment.session_id,
            student_id=enrollment.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            reason_code=cmd.reason_code,
            effective_at=run_at,
            occurred_at=now,
            metadata={"outcome": cmd.outcome, "scheduled_by": "admin"},
        )
        if self._roster_notifier is None:
            return
        try:
            await self._roster_notifier.roster_changed(
                change="cancellation_scheduled",
                session_id=enrollment.session_id,
                student_id=enrollment.student_id,
                enrollment_id=enrollment.enrollment_id,
                actor_id=cmd.actor_id,
            )
        except Exception:
            log.warning(
                "enrollment.roster_notification_failed",
                extra={
                    "change": "cancellation_scheduled",
                    "enrollment_id": enrollment.enrollment_id,
                },
            )


class CancelScheduledAdminDrop:
    """Undo a scheduled drop before it fires (issue #820).

    Order matters: clear the marker FIRST. The marker is what every surface
    reads and what the worker's "still pending?" check keys off, so a crash
    between the two writes leaves a queued action whose enrollment no longer
    looks pending — which the worker treats as "already ended" and retires
    harmlessly. The reverse order could leave a row advertising an end date
    that nothing will ever perform.
    """

    def __init__(
        self,
        *,
        enrollments: PeriodEndDropEnrollmentWriter,
        scheduled_actions: ScheduledEnrollmentActionRepository,
    ) -> None:
        self._enrollments = enrollments
        self._scheduled_actions = scheduled_actions

    async def execute(self, *, enrollment_id: str, actor_id: str) -> None:
        cleared = await self._enrollments.clear_pending_cancellation(enrollment_id)
        if cleared is None:
            raise EnrollmentNotWithdrawable(
                "This enrollment has no scheduled drop to cancel.",
                enrollment_id=enrollment_id,
                status="unknown",
            )
        await self._scheduled_actions.cancel_pending_for_enrollment(
            enrollment_id, reason=f"admin_cancelled_scheduled_drop:{actor_id}"
        )


class ProcessScheduledAdminDropActionsResult(BaseModel):
    model_config = {"frozen": True}
    processed: int = 0
    succeeded: int = 0
    skipped_already_ended: int = 0
    #: Attempt failed but the row is still pending and will be retried.
    retried: int = 0
    failed: int = 0


class ProcessScheduledAdminDropActions:
    def __init__(
        self,
        *,
        scheduled_actions: ScheduledEnrollmentActionRepository,
        enrollments: PeriodEndDropEnrollmentWriter,
        withdraw_enrollment: WithdrawEnrollmentExecutor,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._scheduled_actions = scheduled_actions
        self._enrollments = enrollments
        self._withdraw = withdraw_enrollment
        self._now = clock

    async def execute(
        self, *, now: datetime | None = None, limit: int = 50
    ) -> ProcessScheduledAdminDropActionsResult:
        attempted_at = now or self._now()
        actions = [
            a
            for a in await self._scheduled_actions.list_due(
                now=attempted_at, limit=limit, action_type=ACTION_TYPE
            )
            if a.action_type == ACTION_TYPE
        ]
        succeeded = skipped = retried = failed = 0
        for action in actions:
            try:
                outcome = await self._run_one(action, attempted_at=attempted_at)
            except Exception as exc:
                log.exception(
                    "scheduled_admin_drop_failed",
                    extra={"action_id": action.action_id, "enrollment_id": action.enrollment_id},
                )
                if action.attempt_count + 1 < MAX_ATTEMPTS:
                    await self._scheduled_actions.mark_retry_pending(
                        action.action_id, attempted_at=attempted_at, error=str(exc)[:500]
                    )
                    retried += 1
                else:
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
        return ProcessScheduledAdminDropActionsResult(
            processed=len(actions),
            succeeded=succeeded,
            skipped_already_ended=skipped,
            retried=retried,
            failed=failed,
        )

    async def _run_one(self, action: ScheduledEnrollmentAction, *, attempted_at: datetime) -> str:
        enrollment = await self._enrollments.get(action.enrollment_id)
        if enrollment is None:
            # Terminal: no number of retries makes a deleted enrollment
            # reappear, and a `failed` row reaches a human via the admin
            # attention list (`list_by_statuses(["blocked_capacity","failed"])`).
            await self._scheduled_actions.mark_failed(
                action.action_id, attempted_at=attempted_at, error="enrollment_missing"
            )
            return "failed"
        if enrollment.status not in LIVE or enrollment.pending_cancellation_at is None:
            # An admin dropped / cancelled the row, or cancelled the schedule,
            # before this fired. Nothing to do — `cancelled`, never `failed`,
            # so nobody chases a drop that already happened.
            await self._scheduled_actions.mark_cancelled(
                action.action_id,
                attempted_at=attempted_at,
                reason=f"enrollment_already_ended:{enrollment.status}",
            )
            return "skipped"
        effective_at = enrollment.pending_cancellation_at or action.run_at
        try:
            await self._withdraw.execute(
                WithdrawEnrollmentCommand(
                    enrollment_id=action.enrollment_id,
                    effective_at=effective_at,
                    # `outcome` has a non-null default on the command; an old
                    # row written before this field existed falls back to the
                    # money-neutral option rather than issuing a credit.
                    outcome=action.outcome or "adjustment",
                    actor_id=action.actor_id or "system",
                    reason=action.reason or "Dropped at end of period",
                    reason_code=action.reason_code,
                )
            )
        except EnrollmentNotWithdrawable:
            # Lost the CAS to a concurrent departure between the read above
            # and the withdraw. Same disposition as the status check.
            await self._scheduled_actions.mark_cancelled(
                action.action_id,
                attempted_at=attempted_at,
                reason="enrollment_already_ended:race",
            )
            return "skipped"
        # The row is withdrawn; the marker would otherwise keep advertising a
        # future end date on a row that has already ended.
        await self._enrollments.clear_pending_cancellation(action.enrollment_id)
        await self._scheduled_actions.mark_succeeded(action.action_id, attempted_at=attempted_at)
        return "succeeded"


__all__ = [
    "ACTION_TYPE",
    "MAX_ATTEMPTS",
    "CancelScheduledAdminDrop",
    "PeriodEndDropEnrollmentWriter",
    "ProcessScheduledAdminDropActions",
    "ProcessScheduledAdminDropActionsResult",
    "ScheduleAdminDropAtPeriodEnd",
    "ScheduleAdminDropAtPeriodEndCommand",
    "ScheduleAdminDropAtPeriodEndResult",
    "WithdrawEnrollmentExecutor",
]
