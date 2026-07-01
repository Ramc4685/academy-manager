from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import BillingDeferral
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DecidePauseRequestCommand,
    PauseRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)


def _now() -> datetime:
    return datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


def _request(
    pause_kind: str = "fixed",
    *,
    status: str = "pending",
    resume_on: date | None = date(2026, 7, 15),
    parent_id: str = "parent-1",
) -> PauseRequest:
    return PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id=parent_id,
        pause_kind=pause_kind,  # type: ignore[arg-type]
        resume_on=resume_on,
        review_on=date(2026, 7, 1) if pause_kind == "indefinite" else None,
        reason="summer",
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
    )


@pytest.mark.asyncio
async def test_approve_fixed_pause_pauses_roster_autopay_and_schedules_resume() -> None:
    """Slice B: pause approval toggles the parent's app-owned
    autopay_enrollment_status to paused — there is no Stripe subscription
    collection to pause any more."""
    pause_requests = _FakePauseRequests(_request())
    pause_enrollment = _FakePauseEnrollment()
    scheduled = _FakeScheduledActions()
    deferrals = _FakeBillingDeferrals()
    parent_autopay = _FakeParentAutopay()
    use_case = ApprovePauseRequest(
        pause_requests=pause_requests,
        pause_enrollment=pause_enrollment,
        scheduled_actions=scheduled,
        billing_deferrals=deferrals,
        parent_autopay=parent_autopay,
        academy_id="acad-1",
        clock=_now,
    )

    approved = await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert approved.status == "approved"
    assert pause_enrollment.enrollment_ids == ["enr-1"]
    assert parent_autopay.paused == ["parent-1"]
    assert len(scheduled.actions) == 1
    action = scheduled.actions[0]
    assert action.action_type == "resume_from_pause"
    assert action.enrollment_id == "enr-1"
    assert action.pause_request_id == "pause-1"
    assert action.run_at == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert len(deferrals.rows) == 1
    assert deferrals.rows[0].deferral_type == "fixed_pause"
    assert deferrals.rows[0].resume_on == date(2026, 7, 15)
    assert deferrals.rows[0].billing_period == "2026-07"


@pytest.mark.asyncio
async def test_approve_indefinite_pause_does_not_schedule_resume() -> None:
    scheduled = _FakeScheduledActions()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request("indefinite", resume_on=None)),
        pause_enrollment=_FakePauseEnrollment(),
        scheduled_actions=scheduled,
        billing_deferrals=_FakeBillingDeferrals(),
        parent_autopay=_FakeParentAutopay(),
        academy_id="acad-1",
        clock=_now,
    )

    await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert scheduled.actions == []


@pytest.mark.asyncio
async def test_approve_pause_without_parent_autopay_gateway_still_pauses_roster() -> None:
    pause_enrollment = _FakePauseEnrollment()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request()),
        pause_enrollment=pause_enrollment,
        scheduled_actions=_FakeScheduledActions(),
        academy_id="acad-1",
        clock=_now,
    )

    await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert pause_enrollment.enrollment_ids == ["enr-1"]


@pytest.mark.asyncio
async def test_approve_already_approved_pause_is_idempotent() -> None:
    pause_enrollment = _FakePauseEnrollment()
    scheduled = _FakeScheduledActions()
    parent_autopay = _FakeParentAutopay()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request(status="approved")),
        pause_enrollment=pause_enrollment,
        scheduled_actions=scheduled,
        parent_autopay=parent_autopay,
        academy_id="acad-1",
        clock=_now,
    )

    approved = await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert approved.status == "approved"
    assert pause_enrollment.enrollment_ids == []
    assert scheduled.actions == []
    assert parent_autopay.paused == []


@dataclass
class _FakePauseRequests:
    request: PauseRequest
    approved: bool = False

    async def get(self, pause_request_id: str) -> PauseRequest | None:
        return self.request if pause_request_id == self.request.pause_request_id else None

    async def approve(self, pause_request_id: str, *, admin_id: str) -> PauseRequest:
        self.approved = True
        self.request = self.request.model_copy(
            update={"status": "approved", "decided_by": admin_id, "decided_at": _now()}
        )
        return self.request


@dataclass
class _FakePauseEnrollment:
    enrollment_ids: list[str] = field(default_factory=list)

    async def execute(self, cmd) -> None:
        self.enrollment_ids.append(cmd.enrollment_id)


@dataclass
class _FakeScheduledActions:
    actions: list[ScheduledEnrollmentAction] = field(default_factory=list)

    async def add(self, action: ScheduledEnrollmentAction) -> None:
        self.actions.append(action)


@dataclass
class _FakeBillingDeferrals:
    rows: list[BillingDeferral] = field(default_factory=list)

    async def add(self, deferral: BillingDeferral) -> None:
        self.rows.append(deferral)


@dataclass
class _FakeParentAutopay:
    paused: list[str] = field(default_factory=list)

    async def set_enrollment_status(self, *, parent_id: str, status: str) -> None:
        assert status == "paused"
        self.paused.append(parent_id)
