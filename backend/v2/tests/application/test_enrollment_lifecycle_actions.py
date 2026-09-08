from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    PauseEnrollment,
    PauseEnrollmentCommand,
    ResumeEnrollment,
    TransferEnrollment,
    TransferEnrollmentCommand,
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotTransferable
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry


def _effective() -> datetime:
    return datetime(2026, 5, 25, 0, 0, tzinfo=UTC)


def _now() -> datetime:
    return datetime(2026, 5, 23, 15, 30, tzinfo=UTC)


def _enrollment(status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id="enr-1",
        academy_id="acad",
        session_id="sess-1",
        student_id="stu-1",
        status=status,  # type: ignore[arg-type]
    )


@dataclass
class FakeEnrollments:
    rows: dict[str, Enrollment]

    async def create(self, enrollment: Enrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def update_status(self, enrollment_id: str, status: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(update={"status": status})

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(
            update={"session_id": session_id}
        )

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (
                enrollment
                for enrollment in self.rows.values()
                if enrollment.session_id == session_id and enrollment.student_id == student_id
            ),
            None,
        )


@dataclass
class FakeSessions:
    reserved: dict[str, int] = field(default_factory=lambda: {"sess-1": 1})
    sessions: dict[str, Session] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)


@dataclass
class FakeStudents:
    rows: dict[str, Student]

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self.rows[student_id] for student_id in student_ids if student_id in self.rows]


@dataclass
class FakeWaitlist:
    entries: list[WaitlistEntry] = field(default_factory=list)

    async def add(self, entry: WaitlistEntry) -> None:
        self.entries.append(entry)

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        waiting = [
            entry
            for entry in self.entries
            if entry.session_id == session_id and entry.status == "waiting"
        ]
        return sorted(waiting, key=lambda entry: entry.joined_at)[0] if waiting else None

    async def update_status(self, waitlist_id: str, status: str) -> None:
        self.entries = [
            entry.model_copy(update={"status": status})
            if entry.waitlist_id == waitlist_id
            else entry
            for entry in self.entries
        ]

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry.session_id == session_id
                and entry.student_id == student_id
                and entry.status == "waiting"
            ),
            None,
        )

    async def remove_waiting_for_session_student(self, session_id: str, student_id: str) -> None:
        self.entries = [
            entry.model_copy(update={"status": "removed"})
            if entry.session_id == session_id
            and entry.student_id == student_id
            and entry.status == "waiting"
            else entry
            for entry in self.entries
        ]


@dataclass
class FakeEnrollmentEvents:
    rows: list[EnrollmentLifecycleEvent] = field(default_factory=list)

    async def record(self, event: EnrollmentLifecycleEvent) -> None:
        self.rows.append(event)

    async def list_for_enrollment(self, enrollment_id: str) -> list[EnrollmentLifecycleEvent]:
        # Mirrors the Mongo repo: ascending by occurred_at.
        rows = [e for e in self.rows if e.enrollment_id == enrollment_id]
        return sorted(rows, key=lambda e: (e.occurred_at, e.event_id))


@dataclass
class FakeOutbox:
    rows: list[Any] = field(default_factory=list)

    async def append(self, event: Any) -> None:
        self.rows.append(event)


@dataclass
class RecordingMoveBillingSync:
    """``EnrollmentMoveBillingSync`` fake (issue #669): records the call and
    answers the way the production adapter does."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False
    result: str = "credit:1250"

    async def apply_move(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("billing down")
        self.calls.append(kwargs)
        return {
            "billing_policy": "move_proration_current_period",
            "billing_result": self.result,
            "metadata": {
                "outcome": "credited",
                "delta_cents": "-1250",
                "credit_id": "credit-move-1",
            },
        }


@dataclass
class FakeLifecycleBilling:
    async def record_withdrawal_decision(
        self,
        *,
        enrollment: Enrollment,
        outcome: str,
        effective_at: datetime,
        actor_id: str,
        reason: str,
    ):
        assert enrollment.enrollment_id == "enr-1"
        assert outcome == "refund"
        assert effective_at == _effective()
        assert actor_id == "admin-1"
        assert reason == "moving away"
        return {
            "billing_policy": "withdrawal_refund",
            "billing_result": "refund_requested",
            "metadata": {"outcome": "refund"},
        }


@pytest.mark.asyncio
async def test_pause_releases_seat_waitlists_student_and_records_effective_date() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions()
    waitlist = FakeWaitlist()
    events = FakeEnrollmentEvents()

    use_case = PauseEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        students=FakeStudents(
            rows={
                "stu-1": Student(
                    student_id="stu-1", academy_id="acad", parent_id="parent-1", full_name="Alice"
                )
            }
        ),
        waitlist=waitlist,
        enrollment_events=events,
        clock=_now,
    )

    await use_case.execute(
        PauseEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=_effective(),
            actor_id="admin-1",
            reason="medical pause",
        )
    )

    assert enrollments.rows["enr-1"].status == "paused"
    assert sessions.reserved["sess-1"] == 0
    assert len(waitlist.entries) == 1
    assert waitlist.entries[0].session_id == "sess-1"
    assert waitlist.entries[0].student_id == "stu-1"
    assert waitlist.entries[0].parent_id == "parent-1"
    assert len(events.rows) == 1
    event = events.rows[0]
    assert event.event_type == "paused"
    assert event.effective_at == _effective()
    assert event.occurred_at == _now()
    assert event.billing_policy == "release_seat_waitlist_stop_billing"
    assert event.billing_result == "future_billing_stopped"
    assert event.waitlist_id == waitlist.entries[0].waitlist_id


@pytest.mark.asyncio
async def test_resume_clears_pause_waitlist_and_reserves_seat() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment("paused")})
    sessions = FakeSessions(reserved={"sess-1": 0})
    waitlist = FakeWaitlist(
        entries=[
            WaitlistEntry(
                waitlist_id="wait-1",
                academy_id="acad",
                session_id="sess-1",
                student_id="stu-1",
                parent_id="parent-1",
                joined_at=_now(),
                status="waiting",
            )
        ]
    )

    use_case = ResumeEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        waitlist=waitlist,
        enrollment_events=FakeEnrollmentEvents(),
        clock=_now,
    )

    await use_case.execute("enr-1", actor_id="admin-1", reason="returning")

    assert enrollments.rows["enr-1"].status == "active"
    assert sessions.reserved["sess-1"] == 1
    assert [entry.status for entry in waitlist.entries] == ["removed"]


@pytest.mark.asyncio
async def test_pause_resume_pause_keeps_one_active_waitlist_row() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions()
    waitlist = FakeWaitlist()
    events = FakeEnrollmentEvents()
    students = FakeStudents(
        rows={
            "stu-1": Student(
                student_id="stu-1", academy_id="acad", parent_id="parent-1", full_name="Alice"
            )
        }
    )
    pause = PauseEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        students=students,
        waitlist=waitlist,
        enrollment_events=events,
        clock=_now,
    )
    resume = ResumeEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        waitlist=waitlist,
        enrollment_events=events,
        clock=_now,
    )

    await pause.execute(PauseEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))
    await resume.execute("enr-1", actor_id="admin-1")
    await pause.execute(PauseEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))

    waiting = [entry for entry in waitlist.entries if entry.status == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].student_id == "stu-1"
    assert sessions.reserved["sess-1"] == 0


@pytest.mark.asyncio
async def test_move_records_effective_date_and_billing_proration_result() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    sessions = FakeSessions()
    billing_sync = RecordingMoveBillingSync()

    use_case = TransferEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        enrollment_events=events,
        billing_sync=billing_sync,
        clock=_now,
    )

    await use_case.execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1",
            target_session_id="sess-2",
            effective_at=_effective(),
            actor_id="admin-1",
            reason="schedule change",
        )
    )

    assert enrollments.rows["enr-1"].session_id == "sess-2"
    assert sessions.reserved == {"sess-1": 0, "sess-2": 1}
    # Billing got the real transition: old session, new session, effective date.
    assert billing_sync.calls == [
        {
            "enrollment_id": "enr-1",
            "from_session_id": "sess-1",
            "to_session_id": "sess-2",
            "effective_at": _effective(),
            "reason": "schedule change",
            "actor_id": "admin-1",
            "effective_date": None,
            "move_seq": 0,
        }
    ]
    event = events.rows[0]
    assert event.event_type == "moved"
    assert event.effective_at == _effective()
    assert event.from_session_id == "sess-1"
    assert event.to_session_id == "sess-2"
    assert event.billing_policy == "move_proration_current_period"
    assert event.billing_result == "credit:1250"
    assert event.credit_id == "credit-move-1"
    assert event.metadata == {
        "outcome": "credited",
        "delta_cents": "-1250",
        "credit_id": "credit-move-1",
        "move_seq": "0",
    }


@pytest.mark.asyncio
async def test_move_billing_failure_is_recorded_not_raised() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    sessions = FakeSessions()

    use_case = TransferEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        enrollment_events=events,
        billing_sync=RecordingMoveBillingSync(fail=True),
        clock=_now,
    )

    moved = await use_case.execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1",
            target_session_id="sess-2",
            effective_at=_effective(),
            actor_id="admin-1",
        )
    )

    assert moved.session_id == "sess-2"
    assert sessions.reserved == {"sess-1": 0, "sess-2": 1}
    assert events.rows[0].billing_result == "billing_sync_failed"


@pytest.mark.asyncio
async def test_move_without_billing_sync_reports_unwired() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()

    await TransferEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        enrollment_events=events,
        clock=_now,
    ).execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1", target_session_id="sess-2", actor_id="admin-1"
        )
    )

    assert events.rows[0].billing_result == "billing_sync_unwired"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "withdrawn"])
async def test_move_refuses_a_dead_enrollment_before_any_side_effect(status: str) -> None:
    """#669 review: a cancelled row holds no seat and is not attending, so a
    transfer must not consume a target seat nor bill a move proration."""
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment(status)})
    sessions = FakeSessions()
    billing_sync = RecordingMoveBillingSync()
    events = FakeEnrollmentEvents()

    with pytest.raises(EnrollmentNotTransferable):
        await TransferEnrollment(
            enrollments=enrollments,
            sessions=sessions,
            enrollment_events=events,
            billing_sync=billing_sync,
            clock=_now,
        ).execute(
            TransferEnrollmentCommand(
                enrollment_id="enr-1", target_session_id="sess-2", actor_id="admin-1"
            )
        )

    assert enrollments.rows["enr-1"].session_id == "sess-1"
    assert sessions.reserved == {"sess-1": 1}  # no seat taken, none released
    assert billing_sync.calls == []
    assert events.rows == []


@pytest.mark.asyncio
async def test_second_move_to_the_same_session_carries_its_own_move_seq() -> None:
    """A→B, B→A, A→B in one period: the third move must not reuse the first
    move's billing idempotency scope (#669 review)."""
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    billing_sync = RecordingMoveBillingSync()
    use_case = TransferEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        enrollment_events=events,
        billing_sync=billing_sync,
        clock=_now,
    )

    for target in ("sess-2", "sess-1", "sess-2"):
        await use_case.execute(
            TransferEnrollmentCommand(
                enrollment_id="enr-1", target_session_id=target, actor_id="admin-1"
            )
        )

    assert [call["move_seq"] for call in billing_sync.calls] == [0, 1, 2]
    assert [event.metadata["move_seq"] for event in events.rows] == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_repeat_transfer_retries_a_failed_move_billing_sync() -> None:
    """The roster already moved, so the only way back to the money is to let a
    repeat transfer re-drive billing instead of returning early (#669 review)."""
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    failing = RecordingMoveBillingSync(fail=True)
    await TransferEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        enrollment_events=events,
        billing_sync=failing,
        clock=_now,
    ).execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1",
            target_session_id="sess-2",
            effective_at=_effective(),
            effective_date=date(2026, 5, 25),
            actor_id="admin-1",
        )
    )
    assert events.rows[-1].billing_result == "billing_sync_failed"

    healthy = RecordingMoveBillingSync()
    again = await TransferEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        enrollment_events=events,
        billing_sync=healthy,
        clock=_now,
    ).execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1", target_session_id="sess-2", actor_id="admin-1"
        )
    )

    assert again.session_id == "sess-2"  # roster unchanged, no second seat
    # Same move re-driven: same sides, same seq (so billing stays idempotent).
    assert healthy.calls == [
        {
            "enrollment_id": "enr-1",
            "from_session_id": "sess-1",
            "to_session_id": "sess-2",
            "effective_at": _effective(),
            "reason": "",
            "actor_id": "admin-1",
            "effective_date": date(2026, 5, 25),
            "move_seq": 0,
        }
    ]
    assert events.rows[-1].billing_result == "credit:1250"
    assert events.rows[-1].metadata["retry_of_event_id"] == events.rows[0].event_id


@pytest.mark.asyncio
async def test_repeat_transfer_after_a_successful_move_stays_a_no_op() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    billing_sync = RecordingMoveBillingSync()
    use_case = TransferEnrollment(
        enrollments=enrollments,
        sessions=FakeSessions(),
        enrollment_events=events,
        billing_sync=billing_sync,
        clock=_now,
    )
    cmd = TransferEnrollmentCommand(
        enrollment_id="enr-1", target_session_id="sess-2", actor_id="admin-1"
    )

    await use_case.execute(cmd)
    await use_case.execute(cmd)

    assert len(billing_sync.calls) == 1
    assert len(events.rows) == 1


@pytest.mark.asyncio
async def test_withdraw_records_admin_selected_outcome_and_effective_date() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()

    use_case = WithdrawEnrollment(
        enrollments=enrollments,
        enrollment_events=events,
        billing=FakeLifecycleBilling(),
        clock=_now,
    )

    await use_case.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=_effective(),
            outcome="refund",
            actor_id="admin-1",
            reason="moving away",
        )
    )

    assert enrollments.rows["enr-1"].status == "withdrawn"
    event = events.rows[0]
    assert event.event_type == "withdrawn"
    assert event.effective_at == _effective()
    assert event.actor_id == "admin-1"
    assert event.reason == "moving away"
    assert event.billing_policy == "withdrawal_refund"
    assert event.billing_result == "refund_requested"
    assert event.metadata == {"outcome": "refund"}


@pytest.mark.asyncio
async def test_remove_records_reason_actor_and_effective_date() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions()
    events = FakeEnrollmentEvents()

    use_case = CancelEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        outbox=FakeOutbox(),
        enrollment_events=events,
        academy_id="acad",
        clock=_now,
    )

    await use_case.execute(
        CancelEnrollmentCommand(
            enrollment_id="enr-1",
            event_type="removed",
            effective_at=_effective(),
            reason="duplicate enrollment",
            actor_id="admin-1",
        )
    )

    assert enrollments.rows["enr-1"].status == "cancelled"
    event = events.rows[0]
    assert event.event_type == "removed"
    assert event.effective_at == _effective()
    assert event.actor_id == "admin-1"
    assert event.reason == "duplicate enrollment"
    assert sessions.reserved["sess-1"] == 0
