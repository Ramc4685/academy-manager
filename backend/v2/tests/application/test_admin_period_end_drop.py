"""Issue #820: an admin "drop at end of period" SCHEDULES the drop.

Before this, the only admin drop path was ``WithdrawEnrollment``, which flips
the status and releases the seat in the same call no matter what
``effective_at`` says — so an academy whose departure policy reads
``no_credit_end_of_period`` dropped the child today and merely labelled it
"end of period". These tests pin both halves of the fix: the request leaves
the row live with a pending marker, and the month-end worker performs the real
drop through ``WithdrawEnrollment`` with the ADMIN actor (never
``cancelled_by="parent"``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_period_end_drop import (
    CancelScheduledAdminDrop,
    ProcessScheduledAdminDropActions,
    ScheduleAdminDropAtPeriodEnd,
    ScheduleAdminDropAtPeriodEndCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotWithdrawable
from backend.v2.contexts.enrollment.domain.models import Enrollment

NOW = datetime(2026, 9, 14, 17, 0, tzinfo=UTC)
#: Last instant of September on the academy's wall clock (America/Chicago),
#: expressed in UTC — the same instant ``_end_of_month`` produces for a parent
#: self-cancel, because both read the academy's zone.
MONTH_END = datetime(2026, 10, 1, 4, 59, 59, 999999, tzinfo=UTC)


def _enrollment(status: str = "active", *, pending: datetime | None = None) -> Enrollment:
    return Enrollment(
        enrollment_id="enr-1",
        academy_id="acad",
        session_id="session-1",
        student_id="student-1",
        status=status,  # type: ignore[arg-type]
        pending_cancellation_at=pending,
    )


class _FakeEnrollments:
    def __init__(self, enrollment: Enrollment | None) -> None:
        self.enrollment = enrollment
        self.cleared: list[str] = []

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.enrollment

    async def mark_pending_cancellation_by_admin(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        pending_cancellation_at: datetime,
        requested_at: datetime,
    ) -> Enrollment | None:
        current = self.enrollment
        if current is None or current.pending_cancellation_at is not None:
            return None
        if current.status not in {"active", "paused", "held"}:
            return None
        self.enrollment = current.model_copy(
            update={
                "cancellation_reason": cancellation_reason,
                "pending_cancellation_at": pending_cancellation_at,
                "pending_cancellation_requested_at": requested_at,
            }
        )
        return self.enrollment

    async def clear_pending_cancellation(self, enrollment_id: str) -> Enrollment | None:
        current = self.enrollment
        if current is None or current.pending_cancellation_at is None:
            return None
        self.cleared.append(enrollment_id)
        self.enrollment = current.model_copy(update={"pending_cancellation_at": None})
        return self.enrollment


class _FakeScheduledActions:
    def __init__(self, actions: list[ScheduledEnrollmentAction] | None = None) -> None:
        self.added: list[ScheduledEnrollmentAction] = []
        self.actions = actions or []
        self.statuses: list[tuple[str, str, str | None]] = []
        self.cancelled_for: list[str] = []
        self.cancelled_types: list[str] = []

    async def add(self, action: ScheduledEnrollmentAction) -> None:
        self.added.append(action)

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 50,
        action_type: str | None = None,
    ) -> list[ScheduledEnrollmentAction]:
        # Mirrors the Mongo repo: the STORE applies the type filter, so a
        # worker that forgets to pass its own type is caught here.
        return [
            a
            for a in self.actions
            if a.status == "pending"
            and a.run_at <= now
            and (action_type is None or a.action_type == action_type)
        ][:limit]

    async def mark_succeeded(self, action_id: str, *, attempted_at: datetime) -> None:
        self.statuses.append((action_id, "succeeded", None))

    async def mark_failed(self, action_id: str, *, attempted_at: datetime, error: str) -> None:
        self.statuses.append((action_id, "failed", error))

    async def mark_retry_pending(
        self, action_id: str, *, attempted_at: datetime, error: str
    ) -> None:
        self.statuses.append((action_id, "pending", error))

    async def mark_cancelled(self, action_id: str, *, attempted_at: datetime, reason: str) -> None:
        self.statuses.append((action_id, "cancelled", reason))

    async def cancel_pending_for_enrollment(self, enrollment_id: str, *, reason: str) -> int:
        self.cancelled_for.append(enrollment_id)
        return self._retire(enrollment_id, action_type=None)

    async def cancel_pending_for_enrollment_and_type(
        self, enrollment_id: str, *, action_type: str, reason: str
    ) -> int:
        self.cancelled_for.append(enrollment_id)
        self.cancelled_types.append(action_type)
        return self._retire(enrollment_id, action_type=action_type)

    def _retire(self, enrollment_id: str, *, action_type: str | None) -> int:
        """Mirrors the Mongo repo: cancelling retires the matching PENDING
        rows in the store, so a test can see which rows survived."""
        retired = 0
        for index, action in enumerate(self.actions):
            if (
                action.enrollment_id == enrollment_id
                and action.status == "pending"
                and (action_type is None or action.action_type == action_type)
            ):
                self.actions[index] = action.model_copy(update={"status": "cancelled"})
                retired += 1
        return retired


class _FakeEvents:
    def __init__(self) -> None:
        self.recorded: list[Any] = []

    async def record(self, event: Any) -> None:
        self.recorded.append(event)


class _FakeRosterNotifier:
    def __init__(self) -> None:
        self.changes: list[str] = []

    async def roster_changed(self, *, change: str, **_: Any) -> None:
        self.changes.append(change)


def _schedule(
    enrollments: _FakeEnrollments,
    actions: _FakeScheduledActions,
    *,
    events: _FakeEvents | None = None,
    notifier: _FakeRosterNotifier | None = None,
) -> ScheduleAdminDropAtPeriodEnd:
    async def _tz() -> str | None:
        return "America/Chicago"

    return ScheduleAdminDropAtPeriodEnd(
        enrollments=enrollments,
        scheduled_actions=actions,
        enrollment_events=events,
        roster_notifier=notifier,
        academy_timezone=_tz,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_scheduling_leaves_the_enrollment_live_until_period_end() -> None:
    enrollments = _FakeEnrollments(_enrollment())
    actions = _FakeScheduledActions()
    events = _FakeEvents()
    notifier = _FakeRosterNotifier()

    result = await _schedule(enrollments, actions, events=events, notifier=notifier).execute(
        ScheduleAdminDropAtPeriodEndCommand(
            enrollment_id="enr-1",
            outcome="adjustment",
            actor_id="admin-1",
            reason="Moving away",
            reason_code="moved_away",
        )
    )

    assert result.pending_cancellation_at == MONTH_END
    # The whole point of #820: nothing ended today.
    assert enrollments.enrollment is not None
    assert enrollments.enrollment.status == "active"
    assert enrollments.enrollment.pending_cancellation_at == MONTH_END

    [queued] = actions.added
    assert queued.action_type == "admin_drop_at_period_end"
    assert queued.run_at == MONTH_END
    assert queued.outcome == "adjustment"
    assert queued.actor_id == "admin-1"
    assert queued.reason == "Moving away"
    assert queued.reason_code == "moved_away"

    assert [e.event_type for e in events.recorded] == ["cancellation_scheduled"]
    assert events.recorded[0].actor_id == "admin-1"
    # Coaches learn the row is leaving, NOT that it already left.
    assert notifier.changes == ["cancellation_scheduled"]


@pytest.mark.asyncio
async def test_scheduling_twice_is_refused() -> None:
    enrollments = _FakeEnrollments(_enrollment(pending=MONTH_END))
    actions = _FakeScheduledActions()

    with pytest.raises(EnrollmentNotWithdrawable):
        await _schedule(enrollments, actions).execute(
            ScheduleAdminDropAtPeriodEndCommand(
                enrollment_id="enr-1", actor_id="admin-1", reason="again"
            )
        )
    assert actions.added == []


class _RecordingWithdraw:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    async def execute(self, cmd: Any) -> None:
        self.commands.append(cmd)


def _action(**over: Any) -> ScheduledEnrollmentAction:
    base: dict[str, Any] = dict(
        action_id="action-1",
        academy_id="acad",
        action_type="admin_drop_at_period_end",
        enrollment_id="enr-1",
        run_at=MONTH_END,
        outcome="adjustment",
        actor_id="admin-1",
        reason="Moving away",
        reason_code="moved_away",
        created_at=NOW,
        updated_at=NOW,
    )
    return ScheduledEnrollmentAction(**{**base, **over})


@pytest.mark.asyncio
async def test_worker_drops_through_withdraw_with_the_admin_actor() -> None:
    enrollments = _FakeEnrollments(_enrollment(pending=MONTH_END))
    parent_row = _action(
        action_id="action-parent", action_type="cancel_at_period_end", outcome=None, actor_id=None
    )
    actions = _FakeScheduledActions([_action(), parent_row])
    withdraw = _RecordingWithdraw()

    result = await ProcessScheduledAdminDropActions(
        scheduled_actions=actions,
        enrollments=enrollments,
        withdraw_enrollment=withdraw,
        clock=lambda: MONTH_END + timedelta(minutes=15),
    ).execute()

    assert result.processed == 1
    assert result.succeeded == 1
    [cmd] = withdraw.commands
    assert cmd.enrollment_id == "enr-1"
    assert cmd.effective_at == MONTH_END
    assert cmd.outcome == "adjustment"
    # The admin who asked for it owns the drop, not "parent".
    assert cmd.actor_id == "admin-1"
    assert cmd.reason == "Moving away"
    assert cmd.reason_code == "moved_away"
    assert actions.statuses == [("action-1", "succeeded", None)]
    # The parent queue's row is untouched (issue #675 worker contract).
    assert enrollments.enrollment is not None
    assert enrollments.enrollment.pending_cancellation_at is None


@pytest.mark.asyncio
async def test_worker_stands_down_when_an_admin_already_ended_the_row() -> None:
    enrollments = _FakeEnrollments(_enrollment("withdrawn", pending=None))
    actions = _FakeScheduledActions([_action()])
    withdraw = _RecordingWithdraw()

    result = await ProcessScheduledAdminDropActions(
        scheduled_actions=actions,
        enrollments=enrollments,
        withdraw_enrollment=withdraw,
        clock=lambda: MONTH_END + timedelta(minutes=15),
    ).execute()

    assert result.skipped_already_ended == 1
    assert withdraw.commands == []
    assert actions.statuses[0][1] == "cancelled"


@pytest.mark.asyncio
async def test_admin_can_cancel_a_scheduled_drop() -> None:
    enrollments = _FakeEnrollments(_enrollment(pending=MONTH_END))
    actions = _FakeScheduledActions()

    await CancelScheduledAdminDrop(enrollments=enrollments, scheduled_actions=actions).execute(
        enrollment_id="enr-1", actor_id="admin-1"
    )

    assert enrollments.enrollment is not None
    assert enrollments.enrollment.pending_cancellation_at is None
    assert actions.cancelled_for == ["enr-1"]
    assert actions.cancelled_types == ["admin_drop_at_period_end"]


@pytest.mark.asyncio
async def test_cancelling_a_drop_leaves_an_unrelated_resume_pending() -> None:
    """Undoing a scheduled drop keeps the enrollment LIVE, so it must retire
    ONLY its own action type. Retiring every pending row for the enrollment
    would silently kill a paused family's ``resume_from_pause`` — no resume,
    no error, no log distinguishing it from the intended retirement."""
    enrollments = _FakeEnrollments(_enrollment("paused", pending=MONTH_END))
    resume = _action(
        action_id="action-resume",
        action_type="resume_from_pause",
        pause_request_id="pause-1",
        outcome=None,
        actor_id=None,
        reason=None,
        reason_code=None,
    )
    actions = _FakeScheduledActions([_action(), resume])

    await CancelScheduledAdminDrop(enrollments=enrollments, scheduled_actions=actions).execute(
        enrollment_id="enr-1", actor_id="admin-1"
    )

    survived = {a.action_id: a.status for a in actions.actions}
    assert survived == {"action-1": "cancelled", "action-resume": "pending"}


@pytest.mark.asyncio
async def test_cancelling_a_drop_that_is_not_scheduled_is_refused() -> None:
    enrollments = _FakeEnrollments(_enrollment())
    actions = _FakeScheduledActions()

    with pytest.raises(EnrollmentNotWithdrawable):
        await CancelScheduledAdminDrop(enrollments=enrollments, scheduled_actions=actions).execute(
            enrollment_id="enr-1", actor_id="admin-1"
        )
