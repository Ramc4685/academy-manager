from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.models import Subscription
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
) -> PauseRequest:
    return PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind=pause_kind,  # type: ignore[arg-type]
        resume_on=resume_on,
        reason="summer",
        status=status,  # type: ignore[arg-type]
        created_at=_now(),
    )


def _subscription() -> Subscription:
    return Subscription(
        subscription_id="sub-row-1",
        academy_id="acad-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        session_id="sess-1",
        stripe_subscription_id="sub_123",
        status="active",
        payment_mode="monthly",
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.mark.asyncio
async def test_approve_fixed_pause_pauses_roster_stripe_and_schedules_resume() -> None:
    pause_requests = _FakePauseRequests(_request())
    pause_enrollment = _FakePauseEnrollment()
    scheduled = _FakeScheduledActions()
    stripe = _FakeStripe()
    use_case = ApprovePauseRequest(
        pause_requests=pause_requests,
        pause_enrollment=pause_enrollment,
        scheduled_actions=scheduled,
        subscriptions=_FakeSubscriptions(_subscription()),
        stripe=stripe,
        academy_id="acad-1",
        clock=_now,
    )

    approved = await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert approved.status == "approved"
    assert pause_enrollment.enrollment_ids == ["enr-1"]
    assert stripe.paused == [{"stripe_subscription_id": "sub_123", "behavior": "void"}]
    assert len(scheduled.actions) == 1
    action = scheduled.actions[0]
    assert action.action_type == "resume_from_pause"
    assert action.enrollment_id == "enr-1"
    assert action.pause_request_id == "pause-1"
    assert action.run_at == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_approve_indefinite_pause_does_not_schedule_resume() -> None:
    scheduled = _FakeScheduledActions()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request("indefinite", resume_on=None)),
        pause_enrollment=_FakePauseEnrollment(),
        scheduled_actions=scheduled,
        subscriptions=_FakeSubscriptions(_subscription()),
        stripe=_FakeStripe(),
        academy_id="acad-1",
        clock=_now,
    )

    await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert scheduled.actions == []


@pytest.mark.asyncio
async def test_approve_pause_without_subscription_still_pauses_roster() -> None:
    pause_enrollment = _FakePauseEnrollment()
    stripe = _FakeStripe()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request()),
        pause_enrollment=pause_enrollment,
        scheduled_actions=_FakeScheduledActions(),
        subscriptions=_FakeSubscriptions(None),
        stripe=stripe,
        academy_id="acad-1",
        clock=_now,
    )

    await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert pause_enrollment.enrollment_ids == ["enr-1"]
    assert stripe.paused == []


@pytest.mark.asyncio
async def test_approve_already_approved_pause_is_idempotent() -> None:
    pause_enrollment = _FakePauseEnrollment()
    scheduled = _FakeScheduledActions()
    stripe = _FakeStripe()
    use_case = ApprovePauseRequest(
        pause_requests=_FakePauseRequests(_request(status="approved")),
        pause_enrollment=pause_enrollment,
        scheduled_actions=scheduled,
        subscriptions=_FakeSubscriptions(_subscription()),
        stripe=stripe,
        academy_id="acad-1",
        clock=_now,
    )

    approved = await use_case.execute(
        DecidePauseRequestCommand(pause_request_id="pause-1", admin_id="admin-1")
    )

    assert approved.status == "approved"
    assert pause_enrollment.enrollment_ids == []
    assert scheduled.actions == []
    assert stripe.paused == []


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
class _FakeSubscriptions:
    subscription: Subscription | None

    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None:
        return self.subscription


@dataclass
class _FakeStripe:
    paused: list[dict[str, str]] = field(default_factory=list)

    async def pause_subscription_collection(
        self,
        stripe_subscription_id: str,
        *,
        behavior: str = "void",
    ) -> None:
        self.paused.append({"stripe_subscription_id": stripe_subscription_id, "behavior": behavior})
