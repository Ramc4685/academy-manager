"""Issue #675: the month-end processor performs the real cancel a parent's
end-of-period self-cancel deferred — and stands down when an admin already
ended the enrollment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.process_scheduled_cancellation_actions import (
    MAX_ATTEMPTS,
    ProcessScheduledCancellationActions,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentCancelled
from backend.v2.contexts.enrollment.domain.models import Enrollment

MONTH_END = datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC)
RUN_AT = datetime(2026, 10, 1, 0, 15, tzinfo=UTC)


def _action(action_id: str = "action-1", *, run_at: datetime = MONTH_END, **over: Any):
    base = dict(
        action_id=action_id,
        academy_id="acad",
        action_type="cancel_at_period_end",
        enrollment_id="enr-1",
        pause_request_id=None,
        run_at=run_at,
        created_at=MONTH_END - timedelta(days=20),
        updated_at=MONTH_END - timedelta(days=20),
    )
    return ScheduledEnrollmentAction(**{**base, **over})


def _enrollment(status: str = "active", *, pending: datetime | None = MONTH_END) -> Enrollment:
    return Enrollment(
        enrollment_id="enr-1",
        academy_id="acad",
        session_id="session-1",
        student_id="student-1",
        status=status,  # type: ignore[arg-type]
        cancellation_reason="moving",
        pending_cancellation_at=pending,
    )


class _FakeScheduledActions:
    def __init__(self, actions: list[ScheduledEnrollmentAction]) -> None:
        self._actions = actions
        self.statuses: list[tuple[str, str, str | None]] = []

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 50,
        action_type: str | None = None,
    ) -> list[ScheduledEnrollmentAction]:
        # Mirrors the Mongo repo: the STORE applies the type filter, so a
        # worker that forgets to pass its own type is caught here too.
        return [
            a
            for a in self._actions
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
        self.statuses.append((action_id, "retry_pending", error))

    async def mark_cancelled(self, action_id: str, *, attempted_at: datetime, reason: str) -> None:
        self.statuses.append((action_id, "cancelled", reason))


class _FakeEnrollments:
    """Mirrors ``MongoEnrollmentWriter.complete_pending_cancellation``: CAS on
    active-or-paused AND pending marker set; returns the PRE-image."""

    def __init__(self, rows: dict[str, Enrollment]) -> None:
        self.rows = rows
        self.completed: list[tuple[str, datetime]] = []

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def complete_pending_cancellation(
        self, enrollment_id: str, *, cancelled_at: datetime
    ) -> Enrollment | None:
        before = self.rows.get(enrollment_id)
        if (
            before is None
            or before.status not in {"active", "paused"}
            or before.pending_cancellation_at is None
        ):
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={
                "status": "cancelled",
                "cancelled_by": "parent",
                "cancelled_at": cancelled_at,
                "pending_cancellation_at": None,
            }
        )
        self.completed.append((enrollment_id, cancelled_at))
        return before


@dataclass
class _FakeSessions:
    released: list[str] = field(default_factory=list)

    async def release_seat(self, session_id: str) -> None:
        self.released.append(session_id)


@dataclass
class _FakeOutbox:
    events: list[Any] = field(default_factory=list)

    async def append(self, event: Any, *, session: Any = None) -> None:
        self.events.append(event)


@dataclass
class _FakeEvents:
    rows: list[Any] = field(default_factory=list)

    async def record(self, event: Any) -> None:
        self.rows.append(event)


@dataclass
class _FakeBillingSync:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def apply(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"billing_result": "voided=0,autopay=disabled"}


@dataclass
class _FakeOccurrenceRoster:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def remove_future_for_student(
        self, *, session_id: str, student_id: str, after: datetime
    ) -> int:
        self.calls.append({"session_id": session_id, "student_id": student_id, "after": after})
        return 0


def _use_case(actions, enrollments, **kw):
    defaults = dict(
        sessions=_FakeSessions(),
        outbox=_FakeOutbox(),
        enrollment_events=_FakeEvents(),
        billing_sync=_FakeBillingSync(),
        occurrence_roster=_FakeOccurrenceRoster(),
        clock=lambda: RUN_AT,
    )
    return ProcessScheduledCancellationActions(
        scheduled_actions=actions, enrollments=enrollments, **{**defaults, **kw}
    )


@pytest.mark.asyncio
async def test_due_action_cancels_releases_seat_and_promotes_waitlist() -> None:
    actions = _FakeScheduledActions([_action()])
    enrollments = _FakeEnrollments({"enr-1": _enrollment()})
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    events = _FakeEvents()
    billing = _FakeBillingSync()
    roster = _FakeOccurrenceRoster()
    uc = _use_case(
        actions,
        enrollments,
        sessions=sessions,
        outbox=outbox,
        enrollment_events=events,
        billing_sync=billing,
        occurrence_roster=roster,
    )

    result = await uc.execute()

    assert (result.processed, result.succeeded, result.failed) == (1, 1, 0)
    assert enrollments.rows["enr-1"].status == "cancelled"
    assert enrollments.rows["enr-1"].cancelled_at == MONTH_END
    assert enrollments.rows["enr-1"].cancelled_by == "parent"
    assert enrollments.rows["enr-1"].pending_cancellation_at is None
    assert sessions.released == ["session-1"]
    [event] = outbox.events
    assert isinstance(event, EnrollmentCancelled)
    assert event.payload.reason == "parent_cancel"
    [row] = events.rows
    assert row.event_type == "cancelled"
    assert row.effective_at == MONTH_END
    assert row.billing_result == "voided=0,autopay=disabled"
    # Idempotent second pass of the same sync the request already applied.
    [sync] = billing.calls
    assert sync["transition"] == "cancelled"
    assert sync["effective_at"] == MONTH_END
    assert roster.calls == [
        {"session_id": "session-1", "student_id": "student-1", "after": MONTH_END}
    ]
    assert actions.statuses == [("action-1", "succeeded", None)]


@pytest.mark.asyncio
async def test_not_yet_due_action_is_untouched() -> None:
    actions = _FakeScheduledActions([_action(run_at=RUN_AT + timedelta(hours=1))])
    enrollments = _FakeEnrollments({"enr-1": _enrollment()})
    sessions = _FakeSessions()

    result = await _use_case(actions, enrollments, sessions=sessions).execute()

    assert result.processed == 0
    assert enrollments.rows["enr-1"].status == "active"
    assert sessions.released == []
    assert actions.statuses == []


@pytest.mark.asyncio
async def test_enrollment_already_cancelled_by_admin_marks_action_cancelled_not_failed() -> None:
    actions = _FakeScheduledActions([_action()])
    enrollments = _FakeEnrollments({"enr-1": _enrollment("cancelled")})
    sessions = _FakeSessions()
    outbox = _FakeOutbox()
    billing = _FakeBillingSync()

    result = await _use_case(
        actions, enrollments, sessions=sessions, outbox=outbox, billing_sync=billing
    ).execute()

    assert (result.processed, result.skipped_already_ended, result.failed) == (1, 1, 0)
    # No second seat release, no second promotion, no second billing pass.
    assert sessions.released == []
    assert outbox.events == []
    assert billing.calls == []
    assert actions.statuses == [("action-1", "cancelled", "enrollment_already_ended:cancelled")]


@pytest.mark.asyncio
async def test_paused_enrollment_is_cancelled_without_releasing_its_seat_again() -> None:
    """An admin pause keeps the pending cancellation; the paused row already
    released its seat when it paused."""
    actions = _FakeScheduledActions([_action()])
    enrollments = _FakeEnrollments({"enr-1": _enrollment("paused")})
    sessions = _FakeSessions()
    outbox = _FakeOutbox()

    result = await _use_case(actions, enrollments, sessions=sessions, outbox=outbox).execute()

    assert result.succeeded == 1
    assert enrollments.rows["enr-1"].status == "cancelled"
    assert sessions.released == []
    assert len(outbox.events) == 1


@pytest.mark.asyncio
async def test_missing_enrollment_marks_action_failed() -> None:
    actions = _FakeScheduledActions([_action()])
    result = await _use_case(actions, _FakeEnrollments({})).execute()
    assert result.failed == 1
    assert actions.statuses == [("action-1", "failed", "enrollment_missing")]


@pytest.mark.asyncio
async def test_seat_release_failure_marks_action_failed_and_continues() -> None:
    class _Broken:
        async def release_seat(self, session_id: str) -> None:
            raise RuntimeError("mongo write timed out")

    actions = _FakeScheduledActions([_action(), _action("action-2", enrollment_id="enr-2")])
    enrollments = _FakeEnrollments({"enr-1": _enrollment()})

    result = await _use_case(actions, enrollments, sessions=_Broken()).execute()

    assert result.processed == 2
    # A transient write error leaves the row PENDING for the next hourly tick
    # (#675 follow-up): before this, one Mongo blip parked the cancellation
    # forever with nobody told.
    assert result.retried == 1
    assert result.failed == 1
    assert actions.statuses[0] == ("action-1", "retry_pending", "mongo write timed out")
    assert actions.statuses[1] == ("action-2", "failed", "enrollment_missing")


@pytest.mark.asyncio
async def test_retries_are_bounded_and_the_last_attempt_is_marked_failed() -> None:
    """A permanently broken row must stop retrying and become visible: `failed`
    rows are what the admin attention list reads (#675 follow-up)."""

    class _Broken:
        async def release_seat(self, session_id: str) -> None:
            raise RuntimeError("mongo write timed out")

    exhausted = _action().model_copy(update={"attempt_count": MAX_ATTEMPTS - 1})
    actions = _FakeScheduledActions([exhausted])
    enrollments = _FakeEnrollments({"enr-1": _enrollment()})

    result = await _use_case(actions, enrollments, sessions=_Broken()).execute()

    assert result.retried == 0
    assert result.failed == 1
    assert actions.statuses == [("action-1", "failed", "mongo write timed out")]


@pytest.mark.asyncio
async def test_resume_actions_are_left_to_the_resume_worker() -> None:
    """The mirror of the resume worker's test: neither worker may consume the
    other's due row (#675 follow-up). The filter lives in the repository, and
    the fake enforces it the way Mongo does."""
    actions = _FakeScheduledActions(
        [_action(action_type="resume_from_pause", pause_request_id="pause-1")]
    )
    enrollments = _FakeEnrollments({"enr-1": _enrollment()})
    result = await _use_case(actions, enrollments).execute()
    assert result.processed == 0
    assert actions.statuses == []
    assert enrollments.rows["enr-1"].status == "active"
