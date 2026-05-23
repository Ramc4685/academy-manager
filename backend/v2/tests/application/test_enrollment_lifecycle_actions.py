from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    PauseEnrollment,
    PauseEnrollmentCommand,
    TransferEnrollment,
    TransferEnrollmentCommand,
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
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


@dataclass
class FakeSessions:
    reserved: dict[str, int] = field(default_factory=lambda: {"sess-1": 1})

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


@dataclass
class FakeEnrollmentEvents:
    rows: list[EnrollmentLifecycleEvent] = field(default_factory=list)

    async def record(self, event: EnrollmentLifecycleEvent) -> None:
        self.rows.append(event)


@dataclass
class FakeOutbox:
    rows: list[Any] = field(default_factory=list)

    async def append(self, event: Any) -> None:
        self.rows.append(event)


@dataclass
class FakeLifecycleBilling:
    async def record_move_proration(
        self,
        *,
        enrollment: Enrollment,
        from_session_id: str,
        to_session_id: str,
        effective_at: datetime,
        actor_id: str,
        reason: str | None,
    ):
        assert enrollment.enrollment_id == "enr-1"
        assert from_session_id == "sess-1"
        assert to_session_id == "sess-2"
        assert effective_at == _effective()
        assert actor_id == "admin-1"
        assert reason == "schedule change"
        return {
            "billing_policy": "move_proration",
            "billing_result": "credit:1250",
            "metadata": {"adjustment_cents": "-1250"},
        }

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
            rows={"stu-1": Student(student_id="stu-1", academy_id="acad", parent_id="parent-1", full_name="Alice")}
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
async def test_move_records_effective_date_and_billing_proration_result() -> None:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    events = FakeEnrollmentEvents()
    sessions = FakeSessions()

    use_case = TransferEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        enrollment_events=events,
        billing=FakeLifecycleBilling(),
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
    event = events.rows[0]
    assert event.event_type == "moved"
    assert event.effective_at == _effective()
    assert event.from_session_id == "sess-1"
    assert event.to_session_id == "sess-2"
    assert event.billing_policy == "move_proration"
    assert event.billing_result == "credit:1250"
    assert event.metadata == {"adjustment_cents": "-1250"}


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
