"""Wire the month-end self-cancel processor (issue #675).

Kept out of ``composition/admin.py`` (at its structural line cap). Builds
``ProcessScheduledCancellationActions`` over the same repositories the admin
cancel path uses, so a scheduled cancel and an admin cancel converge on the
same writes: seat release, occurrence-roster cleanup, billing sync,
lifecycle row, ``EnrollmentCancelled`` outbox event, staff alert, and the
close of an open pause/hold billing deferral (issue #782 — a paused or held
row keeps its pending cancellation, so this worker can be the transition that
ends a still-deferred enrollment).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentEventRepository,
    OccurrenceRosterCleanup,
    RosterChangeNotifier,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_period_end_drop import (
    CancelScheduledAdminDrop,
    ProcessScheduledAdminDropActions,
    ScheduleAdminDropAtPeriodEnd,
    WithdrawEnrollmentExecutor,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferralRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.process_scheduled_cancellation_actions import (
    ProcessScheduledCancellationActions,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.shared.events import Outbox


def compose_process_scheduled_cancellation_actions(
    db: Any,
    *,
    scheduled_actions: ScheduledEnrollmentActionRepository,
    outbox: Outbox,
    enrollment_events: EnrollmentEventRepository,
    billing_sync: EnrollmentBillingSync,
    occurrence_roster: OccurrenceRosterCleanup,
    billing_deferrals: BillingDeferralRepository,
    roster_notifier: RosterChangeNotifier | None,
    enrollments: MongoEnrollmentWriter | None = None,
    sessions: MongoSessionWriter | None = None,
) -> ProcessScheduledCancellationActions:
    """Every repo is tenant-scoped at execution time (``tenant_scope`` in the
    scheduler loop) — nothing here captures an academy id."""
    return ProcessScheduledCancellationActions(
        scheduled_actions=scheduled_actions,
        enrollments=enrollments or MongoEnrollmentWriter(db),
        sessions=sessions or MongoSessionWriter(db),
        outbox=outbox,
        enrollment_events=enrollment_events,
        billing_sync=billing_sync,
        occurrence_roster=occurrence_roster,
        billing_deferrals=billing_deferrals,
        roster_notifier=roster_notifier,
    )


@dataclass(frozen=True)
class AdminPeriodEndDrops:
    """The three halves of issue #820, composed together because they share
    one repository pair and are always wired as a set."""

    schedule: ScheduleAdminDropAtPeriodEnd
    cancel: CancelScheduledAdminDrop
    process: ProcessScheduledAdminDropActions


def compose_admin_period_end_drops(
    db: Any,
    *,
    scheduled_actions: ScheduledEnrollmentActionRepository,
    withdraw_enrollment: WithdrawEnrollmentExecutor,
    enrollment_events: EnrollmentEventRepository,
    roster_notifier: RosterChangeNotifier | None,
    academy_timezone: Callable[[], Awaitable[str | None]],
    enrollments: MongoEnrollmentWriter | None = None,
) -> AdminPeriodEndDrops:
    """Issue #820. The processor replays the SAME ``withdraw_enrollment``
    instance the immediate Drop route uses, so a deferred drop and an
    immediate one can never diverge on money, seats or events."""
    writer = enrollments or MongoEnrollmentWriter(db)
    return AdminPeriodEndDrops(
        schedule=ScheduleAdminDropAtPeriodEnd(
            enrollments=writer,
            scheduled_actions=scheduled_actions,
            enrollment_events=enrollment_events,
            roster_notifier=roster_notifier,
            academy_timezone=academy_timezone,
        ),
        cancel=CancelScheduledAdminDrop(enrollments=writer, scheduled_actions=scheduled_actions),
        process=ProcessScheduledAdminDropActions(
            scheduled_actions=scheduled_actions,
            enrollments=writer,
            withdraw_enrollment=withdraw_enrollment,
        ),
    )


def compose_list_stuck_scheduled_actions(
    scheduled_actions: ScheduledEnrollmentActionRepository,
) -> Callable[[], Awaitable[list[ScheduledEnrollmentAction]]]:
    """Reader for the admin attention list: every scheduled enrollment action
    that has stopped moving on its own.

    Issue #675 follow-up: this used to be ``list_by_status("blocked_capacity")``
    — resume actions only. A ``cancel_at_period_end`` that exhausted its
    retries is marked ``failed``, is never picked up again, and left the family
    seated, invoiced and unable to re-request the cancel with nobody told.
    Both statuses are terminal-without-a-human, so both belong here; the
    dashboard route splits them into their own items.
    """

    async def _list() -> list[ScheduledEnrollmentAction]:
        return await scheduled_actions.list_by_statuses(["blocked_capacity", "failed"], limit=100)

    return _list
