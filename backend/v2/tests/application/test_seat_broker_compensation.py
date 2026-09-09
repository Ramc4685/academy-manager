"""Defect #2 — every SeatBroker caller must compensate through
``SeatBroker.release``, not a bare ``release_seat``, when its own write
fails AFTER a successful ``acquire``.

Contract §3.8: ``EditRosterAdd`` already had this compensating block (and is
covered by C7 in ``test_seat_broker_reclaim.py``). ``TransferEnrollment``
acquired the target seat then called ``update_session`` with no
try/except; ``ResumeEnrollment`` acquired then called ``update_status`` with
none either; ``PromoteFromWaitlist`` acquired then wrote the enrollment
(``update_status`` or ``create``) with none either. In every case, when the
acquire came from a hold reclaim, a failure in that follow-up write left a
held child dropped and emailed for a seat that nobody ends up occupying —
and worse, the seat itself was never released, so ``reserved_seats`` stayed
permanently inflated by one (SI violated).

Each test here forces the exact write named above to raise, using a real
``SeatBroker`` backed by the shared contract-enforcing fakes so a full
session with a held row actually goes through a reclaim before the write
fails. Before the fix these all failed: the exception surfaced with the
seat never released (``sessions.release_calls == []`` and
``reserved_seats`` never decremented) and no ``hold_reclaim_orphaned``
event recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    ResumeEnrollment,
    TransferEnrollment,
    TransferEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
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


def _broker(enrollments: FakeEnrollmentWriter, sessions: FakeSessionWriter):
    holds = FakeHoldRepository(enrollments=enrollments)
    billing = FakeBillingSync()
    notifier = FakeHoldNotifier()
    events = FakeEnrollmentEvents()
    broker = SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=FakeDeparturePolicyRepo(),
        billing_sync=billing,
        notifier=notifier,
        enrollment_events=events,
        clock=lambda: NOW,
    )
    return broker, holds, billing, notifier, events


class _Boom(RuntimeError):
    pass


@dataclass
class _RaisingOnUpdateSession(FakeEnrollmentWriter):
    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        raise _Boom("update_session failed")


@dataclass
class _RaisingOnUpdateStatus(FakeEnrollmentWriter):
    async def update_status(self, enrollment_id: str, status: str) -> None:
        raise _Boom("update_status failed")


@dataclass
class _RaisingOnCreate(FakeEnrollmentWriter):
    async def create(self, enrollment) -> None:  # type: ignore[override]
        raise _Boom("create failed")


@pytest.mark.asyncio
async def test_transfer_enrollment_compensates_via_broker_when_update_session_fails() -> None:
    enrollments = _RaisingOnUpdateSession(
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
    broker, _holds, _billing, _notifier, events = _broker(enrollments, sessions)

    transfer = TransferEnrollment(
        enrollments=enrollments, sessions=sessions, seat_broker=broker, clock=lambda: NOW
    )

    with pytest.raises(_Boom):
        await transfer.execute(
            TransferEnrollmentCommand(enrollment_id="moving-1", target_session_id="sess-target")
        )

    # The held row WAS reclaimed (the broker granted before the write blew
    # up) but the failed write must not leave that seat permanently
    # un-accounted-for: compensation releases it.
    assert enrollments.rows["held-1"].status == "withdrawn"
    assert sessions.release_calls == ["sess-target"]
    assert sessions.reserved_seats["sess-target"] == 0
    # And the broker recorded that the reclaim was for nothing.
    event_types = [e.event_type for e in events.rows]
    assert "hold_reclaim_orphaned" in event_types
    # The source enrollment must be untouched — its own write never
    # committed.
    assert enrollments.rows["moving-1"].session_id == "sess-source"


@pytest.mark.asyncio
async def test_resume_enrollment_compensates_via_broker_when_update_status_fails() -> None:
    enrollments = _RaisingOnUpdateStatus(
        rows={
            "paused-1": make_enrollment(
                "paused-1", session_id="sess-1", student_id="stu-paused", status="paused"
            ),
            "held-1": make_enrollment(
                "held-1",
                session_id="sess-1",
                student_id="stu-held",
                status="held",
                hold_started_at=NOW - timedelta(days=10),
            ),
        }
    )
    sessions = FakeSessionWriter(sessions={"sess-1": make_session("sess-1", capacity=1)})
    sessions.reserved_seats["sess-1"] = 1
    broker, _holds, _billing, _notifier, events = _broker(enrollments, sessions)

    resume = ResumeEnrollment(
        enrollments=enrollments, sessions=sessions, seat_broker=broker, clock=lambda: NOW
    )

    with pytest.raises(_Boom):
        await resume.execute("paused-1")

    assert enrollments.rows["held-1"].status == "withdrawn"
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    event_types = [e.event_type for e in events.rows]
    assert "hold_reclaim_orphaned" in event_types
    # The resuming row's own status write never committed.
    assert enrollments.rows["paused-1"].status == "paused"


@pytest.mark.asyncio
async def test_promote_from_waitlist_compensates_via_broker_when_create_fails() -> None:
    enrollments = _RaisingOnCreate(
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
    broker, _holds, _billing, _notifier, events = _broker(enrollments, sessions)

    @dataclass
    class _Waitlist:
        entry: WaitlistEntry

        async def next_waiting(self, session_id: str):
            return self.entry

        async def update_status(self, waitlist_id: str, status: str) -> None:
            raise AssertionError("must not be reached — the enrollment write failed first")

    waitlist = _Waitlist(
        entry=WaitlistEntry(
            waitlist_id="wl-1",
            academy_id="acad",
            session_id="sess-1",
            student_id="stu-waiting",
            parent_id="parent-1",
            joined_at=NOW - timedelta(days=1),
            status="waiting",
        )
    )

    @dataclass
    class _Outbox:
        async def append(self, event) -> None:
            raise AssertionError("must not be reached — the enrollment write failed first")

    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments,
        outbox=_Outbox(),
        academy_id=lambda: "acad",
        seat_broker=broker,
        clock=lambda: NOW,
    )

    with pytest.raises(_Boom):
        await promote.execute("sess-1")

    assert enrollments.rows["held-1"].status == "withdrawn"
    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved_seats["sess-1"] == 0
    event_types = [e.event_type for e in events.rows]
    assert "hold_reclaim_orphaned" in event_types
    # The new enrollment row was never created.
    assert "wl-1" not in enrollments.rows
