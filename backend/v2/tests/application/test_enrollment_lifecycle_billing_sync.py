"""Issue #651: every attendance-stopping transition reaches billing.

Uses the same fakes as ``test_enrollment_lifecycle_actions`` and adds a
recording ``EnrollmentBillingSync`` so each use case can be checked for the
transition and effective date it hands to billing.
"""

from __future__ import annotations

import logging
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
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.errors import SessionNotEnrollable
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
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
class FakeQuery:
    rows: list[Enrollment]

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return await self.for_session_in_statuses(session_id, ["active"])

    async def for_session_in_statuses(
        self, session_id: str, statuses: list[str]
    ) -> list[Enrollment]:
        return [e for e in self.rows if e.session_id == session_id and e.status in statuses]


@dataclass
class FakeSessionWriter(FakeSessions):
    statuses: dict[str, str] = field(default_factory=dict)

    async def update_status(self, session_id: str, status: str) -> None:
        self.statuses[session_id] = status
        if session_id in self.sessions:
            self.sessions[session_id] = self.sessions[session_id].model_copy(
                update={"status": status}
            )


@dataclass
class RecordingDeferrals:
    rows: list[Any] = field(default_factory=list)
    closed: list[tuple[str, str]] = field(default_factory=list)

    async def add(self, deferral: Any) -> None:
        self.rows.append(deferral)

    async def close_active_for_enrollment(
        self, enrollment_id: str, *, closed_at: datetime, closed_by: str, reason: str
    ) -> None:
        self.closed.append((enrollment_id, reason))


@dataclass
class RecordingScheduledActions:
    cancelled: list[tuple[str, str]] = field(default_factory=list)

    async def cancel_pending_for_enrollment(self, enrollment_id: str, *, reason: str) -> int:
        self.cancelled.append((enrollment_id, reason))
        return 1


@dataclass
class RecordingOccurrenceRoster:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def remove_future_for_student(
        self, *, session_id: str, student_id: str, after: datetime
    ) -> int:
        if self.fail:
            raise RuntimeError("roster store down")
        self.calls.append({"session_id": session_id, "student_id": student_id, "after": after})
        return 1


def _session(status: str = "scheduled") -> Session:
    return Session(
        session_id="sess-1",
        academy_id="acad",
        title="Juniors",
        location="Court 1",
        coach_id="coach-1",
        start_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        capacity=8,
        status=status,  # type: ignore[arg-type]
    )


def _paused_enrollment(enrollment_id: str = "enr-2", student_id: str = "stu-2") -> Enrollment:
    return _enrollment("paused").model_copy(
        update={"enrollment_id": enrollment_id, "student_id": student_id}
    )


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


# --- Issue #651 lifecycle-consistency gaps -----------------------------------


@pytest.mark.asyncio
async def test_pause_and_resume_notify_staff_last() -> None:
    """Item 1: pause/resume fire the #612 roster alert as the last statement,
    after billing sync has run (so the alert quotes settled state)."""
    roster = RecordingRoster()
    sync = RecordingBillingSync()
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    await PauseEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        waitlist=FakeWaitlist(),
        billing_sync=sync,
        roster_notifier=roster,
        clock=_now,
    ).execute(PauseEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))
    assert [c["change"] for c in roster.calls] == ["paused"]
    assert roster.calls[0]["enrollment_id"] == "enr-1"
    assert roster.calls[0]["actor_id"] == "admin-1"
    assert sync.calls[-1]["transition"] == "paused"

    await ResumeEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        waitlist=FakeWaitlist(),
        billing_sync=sync,
        roster_notifier=roster,
        clock=_now,
    ).execute("enr-1", actor_id="admin-2")
    assert [c["change"] for c in roster.calls] == ["paused", "resumed"]
    assert roster.calls[1]["actor_id"] == "admin-2"
    assert sync.calls[-1]["transition"] == "resumed"


@pytest.mark.asyncio
async def test_cancel_session_sweeps_paused_rows_without_double_releasing() -> None:
    """Item 2: paused rows are cancelled with everyone else — no seat release
    (they released on pause), deferral closed, scheduled resume cancelled,
    billing told "session_cancelled"."""
    enrollments = DatedEnrollments(rows={"enr-1": _enrollment(), "enr-2": _paused_enrollment()})
    sessions = FakeSessionWriter(reserved={"sess-1": 1})
    deferrals = RecordingDeferrals()
    scheduled = RecordingScheduledActions()
    sync = RecordingBillingSync()
    roster = RecordingRoster()
    cleanup = RecordingOccurrenceRoster()
    outbox = FakeOutbox()
    await CancelSession(
        sessions=sessions,
        enrollments_query=FakeQuery(list(enrollments.rows.values())),
        enrollments_writer=enrollments,
        outbox=outbox,
        academy_id="acad",
        roster_notifier=roster,
        billing_sync=sync,
        billing_deferrals=deferrals,
        scheduled_actions=scheduled,
        occurrence_roster=cleanup,
        clock=_now,
    ).execute(CancelSessionCommand(session_id="sess-1"))

    assert {e.status for e in enrollments.rows.values()} == {"cancelled"}
    # Only the active row released a seat: 1 -> 0, never negative / drifted.
    assert sessions.reserved["sess-1"] == 0
    assert deferrals.closed == [("enr-2", "session_cancelled")]
    assert scheduled.cancelled == [("enr-2", "session_cancelled")]
    assert {(c["enrollment_id"], c["transition"]) for c in sync.calls} == {
        ("enr-1", "session_cancelled"),
        ("enr-2", "session_cancelled"),
    }
    assert [c["change"] for c in roster.calls] == ["session_cancelled", "session_cancelled"]
    assert {c["student_id"] for c in cleanup.calls} == {"stu-1", "stu-2"}
    assert all(c["after"] == _now() for c in cleanup.calls)
    assert len(outbox.rows) == 2


@pytest.mark.asyncio
async def test_withdraw_releases_seat_drops_makeups_and_signals_the_waitlist() -> None:
    """Item 3 + 7: a withdrawn student no longer holds a seat, loses future
    make-up rows, and the seat is offered to the waitlist."""
    sessions = FakeSessions(reserved={"sess-1": 1})
    outbox = FakeOutbox()
    cleanup = RecordingOccurrenceRoster()
    await WithdrawEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=sessions,
        outbox=outbox,
        occurrence_roster=cleanup,
        clock=_now,
    ).execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=EFFECTIVE,
            actor_id="admin-1",
            reason="moving",
        )
    )
    assert sessions.reserved["sess-1"] == 0
    assert len(outbox.rows) == 1
    assert outbox.rows[0].name == "Enrollment.EnrollmentCancelled"
    assert outbox.rows[0].payload.reason == "admin_cancel"
    assert outbox.rows[0].payload.session_id == "sess-1"
    assert cleanup.calls == [{"session_id": "sess-1", "student_id": "stu-1", "after": EFFECTIVE}]


@pytest.mark.asyncio
async def test_withdraw_of_a_paused_row_does_not_release_a_second_seat() -> None:
    sessions = FakeSessions(reserved={"sess-1": 1})
    await WithdrawEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment("paused")}),
        sessions=sessions,
        outbox=FakeOutbox(),
        clock=_now,
    ).execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1", effective_at=EFFECTIVE, actor_id="admin-1", reason="x"
        )
    )
    assert sessions.reserved["sess-1"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paused", "withdrawn"])
async def test_cancel_enrollment_does_not_release_a_seat_it_no_longer_holds(status: str) -> None:
    """Item 4: a paused/withdrawn row already released its seat."""
    sessions = FakeSessions(reserved={"sess-1": 1})
    await CancelEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment(status)}),
        sessions=sessions,
        outbox=FakeOutbox(),
        academy_id="acad",
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    assert sessions.reserved["sess-1"] == 1


@pytest.mark.asyncio
async def test_cancel_enrollment_of_an_active_row_still_releases_its_seat() -> None:
    sessions = FakeSessions(reserved={"sess-1": 1})
    await CancelEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=sessions,
        outbox=FakeOutbox(),
        academy_id="acad",
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    assert sessions.reserved["sess-1"] == 0


def _waiting(waitlist_id: str, student_id: str, joined_at: datetime) -> WaitlistEntry:
    return WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=student_id,
        parent_id=f"parent-{student_id}",
        joined_at=joined_at,
        status="waiting",
    )


@pytest.mark.asyncio
async def test_pause_promotes_the_family_that_was_already_waiting_not_the_paused_student() -> None:
    """Item 5: the released seat goes to whoever was waiting first; the paused
    student joined the queue last and stays paused."""
    waitlist = FakeWaitlist(
        entries=[_waiting("wl-other", "stu-9", datetime(2026, 5, 1, tzinfo=UTC))]
    )
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions(reserved={"sess-1": 1})
    outbox = FakeOutbox()
    await PauseEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        waitlist=waitlist,
        outbox=outbox,
        clock=_now,
    ).execute(PauseEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))

    # The seat-released signal exists and names the session.
    assert [e.name for e in outbox.rows] == ["Enrollment.EnrollmentCancelled"]
    assert outbox.rows[0].payload.session_id == "sess-1"
    # The paused student's own entry is the LAST one in the queue.
    waiting = sorted(
        (e for e in waitlist.entries if e.status == "waiting"), key=lambda e: e.joined_at
    )
    assert [e.student_id for e in waiting] == ["stu-9", "stu-1"]

    # What the on_enrollment_cancelled handler does with that signal:
    promoted = await PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=outbox,
        academy_id=lambda: "acad",
        clock=_now,
    ).execute("sess-1")
    assert promoted == "wl-other"
    assert enrollments.rows["enr-1"].status == "paused"
    assert {e.student_id for e in enrollments.rows.values() if e.status == "active"} == {"stu-9"}
    assert next(e for e in waitlist.entries if e.student_id == "stu-1").status == "waiting"


@pytest.mark.asyncio
async def test_pause_with_nobody_else_waiting_sends_no_seat_signal() -> None:
    """Otherwise the promotion handler would hand the seat straight back to
    the family that just paused."""
    outbox = FakeOutbox()
    await PauseEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=FakeSessions(),
        waitlist=FakeWaitlist(),
        outbox=outbox,
        clock=_now,
    ).execute(PauseEnrollmentCommand(enrollment_id="enr-1"))
    assert outbox.rows == []


@pytest.mark.asyncio
async def test_promote_from_waitlist_refuses_a_cancelled_session() -> None:
    """Item 6a: CancelSession's per-row events must not promote anyone into
    a class that no longer runs."""
    waitlist = FakeWaitlist(entries=[_waiting("wl-1", "stu-9", _now())])
    sessions = FakeSessions(sessions={"sess-1": _session("cancelled")}, reserved={"sess-1": 0})
    enrollments = FakeEnrollments(rows={})
    promoted = await PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=FakeOutbox(),
        academy_id=lambda: "acad",
        clock=_now,
    ).execute("sess-1")
    assert promoted is None
    assert enrollments.rows == {}
    assert sessions.reserved["sess-1"] == 0
    assert waitlist.entries[0].status == "waiting"


@pytest.mark.asyncio
async def test_promote_routes_a_paused_student_through_resume_enrollment() -> None:
    """Item 6b: a paused row at the head of the queue resumes through
    ResumeEnrollment (seat, deferral, autopay, billing sync, "resumed" email)
    and does NOT also get the "a seat opened" email."""
    waitlist = FakeWaitlist(entries=[_waiting("wl-1", "stu-1", _now())])
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment("paused")})
    sessions = FakeSessions(reserved={"sess-1": 0})
    sync = RecordingBillingSync()
    deferrals = RecordingDeferrals()
    roster = RecordingRoster()
    resume = ResumeEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        waitlist=waitlist,
        billing_deferrals=deferrals,
        billing_sync=sync,
        roster_notifier=roster,
        clock=_now,
    )
    promoted = await PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=FakeOutbox(),
        academy_id=lambda: "acad",
        roster_notifier=roster,
        resume=resume,
        clock=_now,
    ).execute("sess-1", actor_id="admin-1")

    assert promoted == "wl-1"
    assert enrollments.rows["enr-1"].status == "active"
    assert sessions.reserved["sess-1"] == 1
    assert sync.calls[0]["transition"] == "resumed"
    assert deferrals.closed == [("enr-1", "resume_succeeded")]
    assert [c["change"] for c in roster.calls] == ["resumed"]
    assert waitlist.entries[0].status == "promoted"


@pytest.mark.asyncio
async def test_promote_of_a_paused_student_into_a_full_class_promotes_nobody() -> None:
    @dataclass
    class FullSessions(FakeSessions):
        async def try_reserve_seat(self, session_id: str) -> bool:
            return False

    waitlist = FakeWaitlist(entries=[_waiting("wl-1", "stu-1", _now())])
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment("paused")})
    sessions = FullSessions()
    promoted = await PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=FakeOutbox(),
        academy_id=lambda: "acad",
        resume=ResumeEnrollment(enrollments=enrollments, sessions=sessions, clock=_now),
        clock=_now,
    ).execute("sess-1")
    assert promoted is None
    assert enrollments.rows["enr-1"].status == "paused"
    assert waitlist.entries[0].status == "waiting"


@pytest.mark.asyncio
async def test_cancel_enrollment_drops_future_makeup_rows_and_survives_cleanup_failure() -> None:
    """Item 7: the cleanup runs after the status write with the effective
    date, and a failing store never fails the cancel."""
    cleanup = RecordingOccurrenceRoster()
    await CancelEnrollment(
        enrollments=FakeEnrollments(rows={"enr-1": _enrollment()}),
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        occurrence_roster=cleanup,
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1", effective_at=EFFECTIVE))
    assert cleanup.calls == [{"session_id": "sess-1", "student_id": "stu-1", "after": EFFECTIVE}]

    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    await CancelEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        outbox=FakeOutbox(),
        academy_id="acad",
        occurrence_roster=RecordingOccurrenceRoster(fail=True),
        clock=_now,
    ).execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    assert enrollments.rows["enr-1"].status == "cancelled"


@pytest.mark.asyncio
async def test_resume_refuses_a_cancelled_session_before_touching_the_seat_counter() -> None:
    """Item 8: SessionNotEnrollable (not "session full"), nothing reserved,
    row stays paused, billing untouched."""
    sessions = FakeSessions(sessions={"sess-1": _session("cancelled")}, reserved={"sess-1": 0})
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment("paused")})
    sync = RecordingBillingSync()
    with pytest.raises(SessionNotEnrollable):
        await ResumeEnrollment(
            enrollments=enrollments, sessions=sessions, billing_sync=sync, clock=_now
        ).execute("enr-1")
    assert sessions.reserved["sess-1"] == 0
    assert enrollments.rows["enr-1"].status == "paused"
    assert sync.calls == []


@pytest.mark.asyncio
async def test_resume_warns_when_autopay_gateway_is_unwired(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Item 10: the warning was dead code behind an `elif`."""
    with caplog.at_level(logging.WARNING):
        await ResumeEnrollment(
            enrollments=FakeEnrollments(rows={"enr-1": _enrollment("paused")}),
            sessions=FakeSessions(),
            billing_sync=RecordingBillingSync(),
            clock=_now,
        ).execute("enr-1")
    assert any("autopay resume skipped" in rec.getMessage() for rec in caplog.records)
