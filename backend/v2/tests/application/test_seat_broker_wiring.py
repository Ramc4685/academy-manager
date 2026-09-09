"""Defect #3 reproduction: SeatBroker.acquire was never called.

Before this fix, ``EditRosterAdd``, ``ResumeEnrollment``, ``TransferEnrollment``
and ``PromoteFromWaitlist`` all called ``SessionWriter.try_reserve_seat``
directly, so a full class with a held seat refused a new child instead of
reclaiming the longest-held hold — the entire point of the departures hold
feature never actually ran. These tests wire each of the four use cases to
a REAL ``SeatBroker`` (backed by the shared contract-enforcing fakes) and
assert the reclaim actually happens end to end: the held row is dropped,
the new occupant is seated, and ``reserved_seats`` never moves (the
handover argument, contract §3.3) — every one of these would refuse with
``CapacityExceeded`` before the fix, because the seat_broker parameter did
not exist on these classes at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    EditRosterAddCommand,
    EditRosterAdd,
    ResumeEnrollment,
    TransferEnrollment,
    TransferEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.events import DomainEvent
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeBillingSync,
    FakeDeparturePolicyRepo,
    FakeEnrollmentEvents,
    FakeEnrollmentWriter,
    FakeHoldNotifier,
    FakeHoldRepository,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@dataclass
class FakeStudentWriter:
    async def ensure_exists(self, student: Any) -> None:
        pass


@dataclass
class FakeWaitlistRepository:
    entries: dict[str, WaitlistEntry] = field(default_factory=dict)
    updated_status: dict[str, str] = field(default_factory=dict)

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        candidates = [
            e
            for e in self.entries.values()
            if e.session_id == session_id and e.status == "waiting"
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda e: e.joined_at)[0]

    async def update_status(self, waitlist_id: str, status: str) -> None:
        self.updated_status[waitlist_id] = status
        e = self.entries[waitlist_id]
        self.entries[waitlist_id] = e.model_copy(update={"status": status})

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None:
        return None

    async def remove_waiting_for_session_student(self, session_id: str, student_id: str) -> None:
        pass

    async def add(self, entry: WaitlistEntry) -> None:
        self.entries[entry.waitlist_id] = entry


@dataclass
class FakeOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    async def append(self, event: DomainEvent) -> None:
        self.events.append(event)


def _broker(sessions: FakeSessionWriter, holds: FakeHoldRepository, billing: FakeBillingSync,
            notifier: FakeHoldNotifier, events: FakeEnrollmentEvents) -> SeatBroker:
    return SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=FakeDeparturePolicyRepo(),
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_edit_roster_add_reclaims_a_held_seat_through_the_broker() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-1",
                student_id="stu-held",
                status="held",
                hold_started_at=NOW - timedelta(days=10),
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = _broker(sessions, holds, billing, notifier, events)

    use_case = EditRosterAdd(
        sessions=sessions,
        enrollments=enrollments,
        students=FakeStudentWriter(),
        academy_id="acad",
        seat_broker=broker,
        clock=lambda: NOW,
    )

    result = await use_case.execute(
        EditRosterAddCommand(
            session_id="sess-1",
            student_id="stu-new",
            parent_id="parent-1",
            full_name="New Kid",
        )
    )

    assert result.status == "active"
    # The held row was reclaimed (dropped), not the new add refused.
    assert enrollments.rows["held-1"].status == "dropped"
    assert [c["transition"] for c in billing.calls] == ["dropped"]
    # Handover: the counter never moves — no try_reserve_seat succeeded a
    # second time and no release_seat ran for the reclaim.
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == []


@pytest.mark.asyncio
async def test_edit_roster_add_without_a_broker_still_refuses_full_capacity() -> None:
    """Sanity check: with NO broker wired (the pre-fix constructor shape),
    a full session with only a held row still refuses — proving the
    reclaim above is really coming from the broker, not from some other
    capacity-check change."""
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1", session_id="sess-1", status="held", hold_started_at=NOW
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    use_case = EditRosterAdd(
        sessions=sessions,
        enrollments=enrollments,
        students=FakeStudentWriter(),
        academy_id="acad",
        clock=lambda: NOW,
    )

    with pytest.raises(CapacityExceeded):
        await use_case.execute(
            EditRosterAddCommand(
                session_id="sess-1",
                student_id="stu-new",
                parent_id="parent-1",
                full_name="New Kid",
            )
        )
    assert enrollments.rows["held-1"].status == "held"


@pytest.mark.asyncio
async def test_resume_enrollment_reclaims_a_held_seat_through_the_broker() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-1",
                student_id="stu-held",
                status="held",
                hold_started_at=NOW - timedelta(days=10),
            ),
            "paused-1": make_enrollment(
                "paused-1", session_id="sess-1", student_id="stu-paused", status="paused"
            ),
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = _broker(sessions, holds, billing, notifier, events)

    resume = ResumeEnrollment(
        enrollments=enrollments, sessions=sessions, seat_broker=broker, clock=lambda: NOW
    )
    await resume.execute("paused-1")

    assert enrollments.rows["paused-1"].status == "active"
    assert enrollments.rows["held-1"].status == "dropped"
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == []


@pytest.mark.asyncio
async def test_transfer_enrollment_reclaims_a_held_seat_in_the_target_through_the_broker() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={
            "moving-1": make_enrollment(
                "moving-1", session_id="sess-source", student_id="stu-moving", status="active"
            ),
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-target",
                student_id="stu-held",
                status="held",
                hold_started_at=NOW - timedelta(days=10),
            ),
        }
    )
    sessions = FakeSessionWriter(
        sessions={
            "sess-source": make_session("sess-source", capacity=5),
            "sess-target": make_session("sess-target", capacity=1),
        }
    )
    sessions.reserved_seats["sess-source"] = 1
    sessions.reserved_seats["sess-target"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = _broker(sessions, holds, billing, notifier, events)

    transfer = TransferEnrollment(
        enrollments=enrollments, sessions=sessions, seat_broker=broker, clock=lambda: NOW
    )
    result = await transfer.execute(
        TransferEnrollmentCommand(enrollment_id="moving-1", target_session_id="sess-target")
    )

    assert result.session_id == "sess-target"
    assert enrollments.rows["held-1"].status == "dropped"
    # Target: handover, net zero. Source: released because the moving row
    # was in SEAT_HOLDING.
    assert sessions.reserved_seats["sess-target"] == 1
    assert sessions.reserved_seats["sess-source"] == 0
    assert sessions.release_calls == ["sess-source"]


@pytest.mark.asyncio
async def test_promote_from_waitlist_reclaims_a_held_seat_through_the_broker() -> None:
    enrollments = FakeEnrollmentWriter(
        rows={
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-1",
                student_id="stu-held",
                status="held",
                hold_started_at=NOW - timedelta(days=10),
            )
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = _broker(sessions, holds, billing, notifier, events)
    waitlist = FakeWaitlistRepository(
        entries={
            "wl-1": WaitlistEntry(
                waitlist_id="wl-1",
                academy_id="acad",
                session_id="sess-1",
                student_id="stu-waiting",
                parent_id="parent-1",
                joined_at=NOW - timedelta(days=1),
                status="waiting",
            )
        }
    )
    outbox = FakeOutbox()

    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=outbox,
        academy_id=lambda: "acad",
        seat_broker=broker,
        clock=lambda: NOW,
    )
    promoted_id = await promote.execute("sess-1")

    assert promoted_id == "wl-1"
    assert waitlist.updated_status["wl-1"] == "promoted"
    assert enrollments.rows["held-1"].status == "dropped"
    assert sessions.reserved_seats["sess-1"] == 1
    assert sessions.release_calls == []
