"""Wire the month-end self-cancel processor (issue #675).

Kept out of ``composition/admin.py`` (at its structural line cap). Builds
``ProcessScheduledCancellationActions`` over the same repositories the admin
cancel path uses, so a scheduled cancel and an admin cancel converge on the
same writes: seat release, occurrence-roster cleanup, billing sync,
lifecycle row, ``EnrollmentCancelled`` outbox event, staff alert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentBillingSync,
    EnrollmentEventRepository,
    OccurrenceRosterCleanup,
    RosterChangeNotifier,
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
        roster_notifier=roster_notifier,
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
