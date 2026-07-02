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
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded


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

    async def list_due(self, *, now: datetime, limit: int = 50) -> list[ScheduledEnrollmentAction]:
        return self.due[:limit]

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
