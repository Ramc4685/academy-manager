from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    EditRosterAdd,
    EditRosterAddCommand,
    JoinWaitlist,
    JoinWaitlistCommand,
    PauseEnrollment,
    PauseEnrollmentCommand,
    ResumeEnrollment,
    TransferEnrollment,
    TransferEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry


@dataclass
class FakeSessions:
    reserved: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserved.append(session_id)
        return True

    async def release_seat(self, session_id: str) -> None:
        self.released.append(session_id)


@dataclass
class FakeStudents:
    rows: list[Student] = field(default_factory=list)

    async def upsert(self, student: Student) -> None:
        self.rows.append(student)


@dataclass
class FakeEnrollments:
    rows: dict[str, Enrollment]
    statuses: list[tuple[str, str]] = field(default_factory=list)
    moves: list[tuple[str, str]] = field(default_factory=list)

    async def create(self, enrollment: Enrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def update_status(self, enrollment_id: str, status: str) -> None:
        self.statuses.append((enrollment_id, status))
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(update={"status": status})

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        self.moves.append((enrollment_id, session_id))
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
class FakeWaitlist:
    entries: dict[str, WaitlistEntry] = field(default_factory=dict)

    async def add(self, entry: WaitlistEntry) -> None:
        self.entries[entry.waitlist_id] = entry

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        waiting = [
            entry
            for entry in self.entries.values()
            if entry.session_id == session_id and entry.status == "waiting"
        ]
        return sorted(waiting, key=lambda entry: entry.joined_at)[0] if waiting else None

    async def update_status(self, waitlist_id: str, status: str) -> None:
        self.entries[waitlist_id] = self.entries[waitlist_id].model_copy(update={"status": status})

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None:
        return next(
            (
                entry
                for entry in self.entries.values()
                if entry.session_id == session_id
                and entry.student_id == student_id
                and entry.status == "waiting"
            ),
            None,
        )

    async def remove_waiting_for_session_student(self, session_id: str, student_id: str) -> None:
        self.entries = {
            waitlist_id: entry.model_copy(update={"status": "removed"})
            if entry.session_id == session_id
            and entry.student_id == student_id
            and entry.status == "waiting"
            else entry
            for waitlist_id, entry in self.entries.items()
        }


@dataclass
class FakeEnrollmentEvents:
    rows: list[EnrollmentLifecycleEvent] = field(default_factory=list)

    async def record(self, event: EnrollmentLifecycleEvent) -> None:
        self.rows.append(event)


@dataclass
class FakeOutbox:
    events: list[object] = field(default_factory=list)

    async def append(self, event: object) -> None:
        self.events.append(event)


def _enrollment(status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id="enr-1",
        academy_id="acad",
        session_id="sess-1",
        student_id="stu-1",
        status=status,  # type: ignore[arg-type]
    )


def _clock() -> datetime:
    return datetime(2026, 5, 21, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_add_to_roster_records_created_event() -> None:
    events = FakeEnrollmentEvents()
    use_case = EditRosterAdd(
        sessions=FakeSessions(),
        enrollments=FakeEnrollments(rows={}),
        students=FakeStudents(),
        enrollment_events=events,
        academy_id="acad",
        clock=_clock,
    )

    enrollment = await use_case.execute(
        EditRosterAddCommand(
            session_id="sess-1",
            student_id="stu-1",
            parent_id="parent-1",
            full_name="Alice",
            actor_id="admin-1",
        )
    )

    assert len(events.rows) == 1
    event = events.rows[0]
    assert event.event_type == "created"
    assert event.enrollment_id == enrollment.enrollment_id
    assert event.session_id == "sess-1"
    assert event.student_id == "stu-1"
    assert event.actor_id == "admin-1"
    assert event.effective_at == _clock()


@pytest.mark.asyncio
async def test_transfer_pause_resume_and_cancel_record_events_only_on_real_transitions() -> None:
    events = FakeEnrollmentEvents()
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions()

    transfer = TransferEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        enrollment_events=events,
        clock=_clock,
    )
    moved = await transfer.execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1",
            target_session_id="sess-2",
            actor_id="admin-1",
            reason="schedule_change",
        )
    )
    await transfer.execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1",
            target_session_id="sess-2",
            actor_id="admin-1",
        )
    )

    pause = PauseEnrollment(enrollments=enrollments, enrollment_events=events, clock=_clock)
    await pause.execute(
        PauseEnrollmentCommand(
            enrollment_id="enr-1",
            actor_id="admin-1",
            reason="medical",
        )
    )
    await pause.execute(PauseEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))

    resume = ResumeEnrollment(enrollments=enrollments, enrollment_events=events, clock=_clock)
    await resume.execute("enr-1", actor_id="admin-1", reason="cleared")
    await resume.execute("enr-1", actor_id="admin-1")

    cancel = CancelEnrollment(
        enrollments=enrollments,
        sessions=sessions,
        outbox=FakeOutbox(),
        enrollment_events=events,
        academy_id="acad",
        clock=_clock,
    )
    await cancel.execute(
        CancelEnrollmentCommand(
            enrollment_id="enr-1",
            reason="admin_cancel",
            actor_id="admin-1",
        )
    )
    await cancel.execute(CancelEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))

    assert moved.session_id == "sess-2"
    assert [event.event_type for event in events.rows] == [
        "moved",
        "paused",
        "resumed",
        "cancelled",
    ]
    assert events.rows[0].from_session_id == "sess-1"
    assert events.rows[0].to_session_id == "sess-2"
    assert events.rows[0].reason == "schedule_change"
    assert events.rows[1].reason == "medical"
    assert events.rows[2].reason == "cleared"
    assert events.rows[3].reason == "admin_cancel"


@pytest.mark.asyncio
async def test_waitlist_and_promotion_record_lifecycle_events() -> None:
    events = FakeEnrollmentEvents()
    waitlist = FakeWaitlist()
    join = JoinWaitlist(
        waitlist=waitlist,
        enrollment_events=events,
        academy_id="acad",
        clock=_clock,
    )

    entry = await join.execute(
        JoinWaitlistCommand(
            session_id="sess-1",
            parent_id="parent-1",
            student_id="stu-1",
            actor_id="parent-1",
            reason="session_full",
        )
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=FakeSessions(),
        enrollments=FakeEnrollments(rows={}),
        outbox=FakeOutbox(),
        enrollment_events=events,
        academy_id=lambda: "acad",
        clock=_clock,
    )
    promoted_id = await promote.execute("sess-1", actor_id="admin-1")

    assert promoted_id == entry.waitlist_id
    assert [event.event_type for event in events.rows] == ["waitlisted", "promoted"]
    assert events.rows[0].waitlist_id == entry.waitlist_id
    assert events.rows[0].reason == "session_full"
    assert events.rows[1].waitlist_id == entry.waitlist_id
    assert events.rows[1].actor_id == "admin-1"
