from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.process_scheduled_resume_actions import (
    ProcessScheduledResumeActions,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded, SessionNotEnrollable


def _now() -> datetime:
    return datetime(2026, 7, 15, 7, 0, tzinfo=UTC)


def _action() -> ScheduledEnrollmentAction:
    return ScheduledEnrollmentAction(
        action_id="action-1",
        academy_id="acad-1",
        action_type="resume_from_pause",
        enrollment_id="enr-1",
        pause_request_id="pause-1",
        run_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.mark.asyncio
async def test_due_resume_action_resumes_roster_and_closes_deferral() -> None:
    """Slice B: the worker no longer resumes a Stripe subscription —
    ResumeEnrollment itself toggles autopay_enrollment_status back to
    active. This worker's job is just roster resume + closing the deferral."""
    actions = _FakeScheduledActions([_action()])
    resume = _FakeResumeEnrollment()
    deferrals = _FakeBillingDeferrals()
    use_case = ProcessScheduledResumeActions(
        scheduled_actions=actions,
        resume_enrollment=resume,
        billing_deferrals=deferrals,
        clock=_now,
    )

    result = await use_case.execute()

    assert result.succeeded == 1
    assert resume.enrollment_ids == ["enr-1"]
    assert actions.statuses == [("action-1", "succeeded")]
    assert deferrals.closed == [("enr-1", "resume_succeeded")]


@pytest.mark.asyncio
async def test_full_class_marks_action_blocked_capacity() -> None:
    actions = _FakeScheduledActions([_action()])
    resume = _FakeResumeEnrollment(capacity_blocked=True)
    deferrals = _FakeBillingDeferrals()
    use_case = ProcessScheduledResumeActions(
        scheduled_actions=actions,
        resume_enrollment=resume,
        billing_deferrals=deferrals,
        clock=_now,
    )

    result = await use_case.execute()

    assert result.blocked_capacity == 1
    assert actions.statuses == [("action-1", "blocked_capacity")]
    assert deferrals.closed == []


@pytest.mark.asyncio
async def test_cancelled_session_marks_action_failed_with_session_cancelled_reason() -> None:
    """Issue #651: the class was cancelled during the pause. Terminal, and
    recorded under its own reason — never as "blocked_capacity"."""
    actions = _FakeScheduledActions([_action()])
    deferrals = _FakeBillingDeferrals()
    use_case = ProcessScheduledResumeActions(
        scheduled_actions=actions,
        resume_enrollment=_FakeResumeEnrollment(session_cancelled=True),
        billing_deferrals=deferrals,
        clock=_now,
    )

    result = await use_case.execute()

    assert result.blocked_session_cancelled == 1
    assert result.blocked_capacity == 0
    assert result.failed == 0
    assert actions.statuses == [("action-1", "failed")]
    assert actions.last_error == "session_cancelled"
    assert deferrals.closed == []


@pytest.mark.asyncio
async def test_deferral_close_failure_marks_action_failed() -> None:
    actions = _FakeScheduledActions([_action()])
    deferrals = _FakeBillingDeferrals(fail=True)
    use_case = ProcessScheduledResumeActions(
        scheduled_actions=actions,
        resume_enrollment=_FakeResumeEnrollment(),
        billing_deferrals=deferrals,
        clock=_now,
    )

    result = await use_case.execute()

    assert result.failed == 1
    assert actions.statuses == [("action-1", "failed")]
    assert "deferral close unavailable" in (actions.last_error or "")


@dataclass
class _FakeScheduledActions:
    due: list[ScheduledEnrollmentAction]
    statuses: list[tuple[str, str]] = field(default_factory=list)
    last_error: str | None = None

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 50,
        action_type: str | None = None,
    ) -> list[ScheduledEnrollmentAction]:
        # Mirrors the Mongo repo: the type filter is applied by the STORE, so
        # a worker that forgets to pass its type is caught here too.
        rows = [a for a in self.due if action_type is None or a.action_type == action_type]
        return rows[:limit]

    async def mark_succeeded(self, action_id: str, *, attempted_at: datetime) -> None:
        self.statuses.append((action_id, "succeeded"))

    async def mark_blocked_capacity(self, action_id: str, *, attempted_at: datetime) -> None:
        self.statuses.append((action_id, "blocked_capacity"))

    async def mark_failed(self, action_id: str, *, attempted_at: datetime, error: str) -> None:
        self.last_error = error
        self.statuses.append((action_id, "failed"))


@dataclass
class _FakeResumeEnrollment:
    capacity_blocked: bool = False
    session_cancelled: bool = False
    enrollment_ids: list[str] = field(default_factory=list)

    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
        close_billing_deferral: bool = True,
    ) -> None:
        if self.capacity_blocked:
            raise CapacityExceeded("session full", session_id="sess-1")
        if self.session_cancelled:
            raise SessionNotEnrollable("cancelled", session_id="sess-1", status="cancelled")
        self.enrollment_ids.append(enrollment_id)


@dataclass
class _FakeBillingDeferrals:
    fail: bool = False
    closed: list[tuple[str, str]] = field(default_factory=list)

    async def close_active_for_enrollment(
        self,
        enrollment_id: str,
        *,
        closed_at: datetime,
        closed_by: str,
        reason: str,
    ) -> None:
        if self.fail:
            raise RuntimeError("deferral close unavailable")
        self.closed.append((enrollment_id, reason))


@pytest.mark.asyncio
async def test_due_cancel_at_period_end_action_is_left_for_the_cancellation_worker() -> None:
    """Issue #675 follow-up (P1). Both workers drain one collection. Before the
    fix this worker took the due cancel row, `ResumeEnrollment` no-opped it (the
    enrollment is not paused) and it was marked `succeeded` — the parent's
    cancellation was destroyed with no error anywhere."""
    cancel_row = ScheduledEnrollmentAction(
        action_id="action-cancel",
        academy_id="acad-1",
        action_type="cancel_at_period_end",
        enrollment_id="enr-9",
        pause_request_id=None,
        run_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    actions = _FakeScheduledActions([cancel_row, _action()])
    resume = _FakeResumeEnrollment()
    use_case = ProcessScheduledResumeActions(
        scheduled_actions=actions,
        resume_enrollment=resume,
        clock=_now,
    )

    result = await use_case.execute()

    assert result.processed == 1
    assert resume.enrollment_ids == ["enr-1"]
    assert actions.statuses == [("action-1", "succeeded")]
    assert all(action_id != "action-cancel" for action_id, _ in actions.statuses)
