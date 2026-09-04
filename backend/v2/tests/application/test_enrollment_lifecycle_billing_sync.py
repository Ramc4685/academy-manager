"""Issue #651: every attendance-stopping transition reaches billing.

Uses the same fakes as ``test_enrollment_lifecycle_actions`` and adds a
recording ``EnrollmentBillingSync`` so each use case can be checked for the
transition and effective date it hands to billing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    CancelSession,
    CancelSessionCommand,
    PauseEnrollment,
    PauseEnrollmentCommand,
    ResumeEnrollment,
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    paused_billing_periods,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    DecidePauseRequestCommand,
    DeclinePauseRequest,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session
from backend.v2.tests.application.test_enrollment_lifecycle_actions import (
    FakeEnrollmentEvents,
    FakeEnrollments,
    FakeOutbox,
    FakeSessions,
    FakeStudents,
    FakeWaitlist,
    _enrollment,
    _now,
)

EFFECTIVE = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@dataclass
class RecordingBillingSync:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def apply(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("billing down")
        self.calls.append(kwargs)
        return {"billing_result": "voided=1,autopay=disabled"}


@dataclass
class RecordingRoster:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def roster_changed(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@dataclass
class DatedEnrollments(FakeEnrollments):
    dates: list[dict[str, Any]] = field(default_factory=list)

    async def set_lifecycle_dates(self, enrollment_id: str, **dates: datetime) -> None:
        self.dates.append({"enrollment_id": enrollment_id, **dates})


@pytest.mark.asyncio
async def test_cancel_enrollment_syncs_billing_persists_date_and_records_result() -> None:
    enrollments = DatedEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    sync = RecordingBillingSync()
    use_case = CancelEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        enrollment_events=events,
        billing_sync=sync,
        clock=_now,
    )
    await use_case.execute(
        CancelEnrollmentCommand(
            enrollment_id="enr-1", reason="admin_cancel", effective_at=EFFECTIVE, actor_id="admin-1"
        )
    )
    assert sync.calls == [
        {
            "enrollment_id": "enr-1",
            "transition": "cancelled",
            "effective_at": EFFECTIVE,
            "reason": "admin_cancel",
            "actor_id": "admin-1",
        }
    ]
    assert enrollments.dates == [{"enrollment_id": "enr-1", "cancelled_at": EFFECTIVE}]
    assert events.rows[0].billing_policy == "current_period_payable_future_voided"
    assert events.rows[0].billing_result == "voided=1,autopay=disabled"


@pytest.mark.asyncio
async def test_cancel_enrollment_for_session_cancelled_reason_uses_that_transition() -> None:
    sync = RecordingBillingSync()
    await CancelEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        billing_sync=sync,
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1", reason="session_cancelled"))
    assert sync.calls[0]["transition"] == "session_cancelled"


@pytest.mark.asyncio
async def test_cancel_still_succeeds_when_billing_sync_raises() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    await CancelEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        enrollment_events=events,
        billing_sync=RecordingBillingSync(fail=True),
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    assert enrollments.rows["enr-1"].status == "cancelled"
    assert events.rows[0].billing_result == "billing_sync_failed"


@pytest.mark.asyncio
async def test_cancel_without_sync_wired_marks_the_event_unwired() -> None:
    events = FakeEnrollmentEvents()
    await CancelEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        enrollment_events=events,
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    assert events.rows[0].billing_result == "billing_sync_unwired"


@pytest.mark.asyncio
async def test_withdraw_syncs_billing_and_never_claims_a_decision_was_recorded() -> None:
    enrollments = DatedEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    sync = RecordingBillingSync()
    await WithdrawEnrollment(
        enrollments=enrollments,
        enrollment_events=events,
        billing_sync=sync,
        clock=_now,
    ).execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=EFFECTIVE,
            outcome="credit",
            actor_id="admin-1",
            reason="moving",
        )
    )
    assert sync.calls[0]["transition"] == "withdrawn"
    assert sync.calls[0]["effective_at"] == EFFECTIVE
    assert enrollments.dates == [{"enrollment_id": "enr-1", "withdrawal_date": EFFECTIVE}]
    assert events.rows[0].billing_result == "decision_not_recorded;voided=1,autopay=disabled"


@pytest.mark.asyncio
async def test_pause_writes_one_deferral_per_paused_month_and_syncs_billing() -> None:
    @dataclass
    class Deferrals:
        rows: list[Any] = field(default_factory=list)

        async def add(self, deferral: Any) -> None:
            self.rows.append(deferral)

    deferrals = Deferrals()
    sync = RecordingBillingSync()
    await PauseEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=FakeSessions(),
        students=FakeStudents(rows={}),
        waitlist=FakeWaitlist(),
        enrollment_events=FakeEnrollmentEvents(),
        billing_deferrals=deferrals,
        billing_sync=sync,
        clock=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    ).execute(
        PauseEnrollmentCommand(
            enrollment_id="enr-1", resume_on=date(2026, 12, 1), reason="travel", actor_id="admin-1"
        )
    )
    assert [d.billing_period for d in deferrals.rows] == ["2026-10", "2026-11"]
    assert all(d.resume_on == date(2026, 12, 1) for d in deferrals.rows)
    assert sync.calls[0]["transition"] == "paused"


@pytest.mark.asyncio
async def test_resume_syncs_billing_as_resumed() -> None:
    sync = RecordingBillingSync()
    await ResumeEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment("paused")}),
        sessions=FakeSessions(),
        waitlist=FakeWaitlist(),
        billing_sync=sync,
        clock=_now,
    ).execute("enr-1", actor_id="admin-1")
    assert sync.calls[0]["transition"] == "resumed"


@pytest.mark.asyncio
async def test_cancel_session_releases_seats_records_events_syncs_billing_and_notifies() -> None:
    @dataclass
    class FakeSessionWriter(FakeSessions):
        statuses: dict[str, str] = field(default_factory=dict)

        async def update_status(self, session_id: str, status: str) -> None:
            self.statuses[session_id] = status

        async def get(self, session_id: str) -> Session | None:
            return None

    @dataclass
    class FakeQuery:
        rows: list[Enrollment]

        async def active_for_session(self, session_id: str) -> list[Enrollment]:
            return [e for e in self.rows if e.session_id == session_id and e.status == "active"]

    enrollments = DatedEnrollments(
        rows={
            "enr-1": _enrollment(),
            "enr-2": _enrollment().model_copy(
                update={"enrollment_id": "enr-2", "student_id": "stu-2"}
            ),
        }
    )
    sessions = FakeSessionWriter(reserved={"sess-1": 2})
    events = FakeEnrollmentEvents()
    sync = RecordingBillingSync()
    roster = RecordingRoster()
    outbox = FakeOutbox()
    await CancelSession(
        sessions=sessions,
        enrollments_query=FakeQuery(list(enrollments.rows.values())),
        enrollments_writer=enrollments,
        outbox=outbox,
        academy_id="acad",
        enrollment_events=events,
        roster_notifier=roster,
        billing_sync=sync,
        clock=_now,
    ).execute(CancelSessionCommand(session_id="sess-1"))

    assert sessions.statuses == {"sess-1": "cancelled"}
    assert sessions.reserved["sess-1"] == 0
    assert {c["enrollment_id"] for c in sync.calls} == {"enr-1", "enr-2"}
    assert all(c["transition"] == "session_cancelled" for c in sync.calls)
    assert [e.event_type for e in events.rows] == ["cancelled", "cancelled"]
    assert all(e.reason == "session_cancelled" for e in events.rows)
    assert [c["change"] for c in roster.calls] == ["session_cancelled", "session_cancelled"]
    assert len(enrollments.dates) == 2
    assert len(outbox.rows) == 2


@pytest.mark.asyncio
async def test_decline_pause_request_notifies_the_parent() -> None:
    @dataclass
    class FakeRequests:
        async def decline(self, pause_request_id: str, *, admin_id: str) -> Any:
            from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
                PauseRequest,
            )

            return PauseRequest(
                pause_request_id=pause_request_id,
                enrollment_id="enr-1",
                parent_id="parent-1",
                session_id="sess-1",
                pause_kind="fixed",
                period="2026-10",
                resume_on=date(2026, 11, 1),
                status="declined",
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            )

    @dataclass
    class Notifier:
        calls: list[dict[str, Any]] = field(default_factory=list)

        async def pause_request_declined(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

    notifier = Notifier()
    await DeclinePauseRequest(pause_requests=FakeRequests(), notifier=notifier).execute(
        DecidePauseRequestCommand(
            pause_request_id="pause-1", admin_id="admin-1", reason="Class full"
        )
    )
    assert notifier.calls == [
        {
            "parent_id": "parent-1",
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "reason": "Class full",
        }
    ]


def test_paused_billing_periods_rules() -> None:
    sep_10 = datetime(2026, 9, 10, tzinfo=UTC)
    # Resume on the 1st: that month is billed again.
    assert paused_billing_periods(
        effective_at=sep_10, resume_on=date(2026, 12, 1), review_on=None
    ) == [
        "2026-10",
        "2026-11",
    ]
    # Resume mid-month: still paused on that month's billing day, so it is skipped too.
    assert paused_billing_periods(
        effective_at=sep_10, resume_on=date(2026, 11, 15), review_on=None
    ) == [
        "2026-10",
        "2026-11",
    ]
    # Resume next month on the 1st: nothing to defer (current month stays payable).
    assert (
        paused_billing_periods(effective_at=sep_10, resume_on=date(2026, 10, 1), review_on=None)
        == []
    )
    # Indefinite pause: through the review month.
    assert paused_billing_periods(
        effective_at=sep_10, resume_on=None, review_on=date(2026, 11, 20)
    ) == [
        "2026-10",
        "2026-11",
    ]
    # Unbounded: nothing (the model forbids an unbounded active deferral anyway).
    assert paused_billing_periods(effective_at=sep_10, resume_on=None, review_on=None) == []
    # Year rollover and the 12-month cap.
    assert paused_billing_periods(
        effective_at=datetime(2026, 11, 3, tzinfo=UTC), resume_on=date(2028, 6, 1), review_on=None
    ) == ["2026-12"] + [f"2027-{m:02d}" for m in range(1, 12)]
