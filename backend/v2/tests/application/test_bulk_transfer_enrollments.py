"""A0-8: bulk roster transfer loops the single-enrollment TransferEnrollment.

Each row must get exactly the single transfer's seat, billing and event
behaviour, and one row's refusal must not undo or block the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    BulkTransferEnrollments,
    BulkTransferEnrollmentsCommand,
    TransferEnrollment,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.tests.application.test_enrollment_lifecycle_actions import (
    FakeEnrollmentEvents,
    FakeEnrollments,
    RecordingMoveBillingSync,
    _now,
)


def _row(enrollment_id: str, status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=f"stu-{enrollment_id}",
        status=status,  # type: ignore[arg-type]
    )


@dataclass
class CappedSessions:
    """Seat counter that refuses past capacity, like SessionWriter.try_reserve_seat."""

    reserved: dict[str, int] = field(default_factory=lambda: {"sess-1": 3})
    capacity: dict[str, int] = field(default_factory=lambda: {"sess-2": 99})

    async def try_reserve_seat(self, session_id: str) -> bool:
        if self.reserved.get(session_id, 0) >= self.capacity.get(session_id, 99):
            return False
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)


def _bulk(enrollments: FakeEnrollments, sessions: CappedSessions, events, billing):
    return BulkTransferEnrollments(
        transfer=TransferEnrollment(
            enrollments=enrollments,
            sessions=sessions,
            enrollment_events=events,
            billing_sync=billing,
            clock=_now,
        )
    )


@pytest.mark.asyncio
async def test_bulk_transfer_moves_each_row_through_the_single_transfer_path() -> None:
    enrollments = FakeEnrollments(rows={"a": _row("a"), "b": _row("b")})
    sessions = CappedSessions(reserved={"sess-1": 2})
    events = FakeEnrollmentEvents()
    billing = RecordingMoveBillingSync()

    result = await _bulk(enrollments, sessions, events, billing).execute(
        BulkTransferEnrollmentsCommand(
            enrollment_ids=["a", "b"], target_session_id="sess-2", actor_id="admin-1"
        )
    )

    assert [r.ok for r in result.results] == [True, True]
    assert result.moved_count == 2 and result.failed_count == 0
    assert {e.session_id for e in enrollments.rows.values()} == {"sess-2"}
    assert sessions.reserved == {"sess-1": 0, "sess-2": 2}
    # Billing proration and the "moved" event ran once per row, as for a single move.
    assert [c["enrollment_id"] for c in billing.calls] == ["a", "b"]
    assert [e.event_type for e in events.rows] == ["moved", "moved"]


@pytest.mark.asyncio
async def test_bulk_transfer_reports_per_row_failures_without_stopping() -> None:
    enrollments = FakeEnrollments(
        rows={"a": _row("a"), "gone": _row("gone", "dropped"), "c": _row("c"), "d": _row("d")}
    )
    # Target has room for exactly two more students.
    sessions = CappedSessions(reserved={"sess-1": 3, "sess-2": 0}, capacity={"sess-2": 2})
    events = FakeEnrollmentEvents()

    result = await _bulk(enrollments, sessions, events, RecordingMoveBillingSync()).execute(
        BulkTransferEnrollmentsCommand(
            enrollment_ids=["a", "gone", "missing", "c", "d"], target_session_id="sess-2"
        )
    )

    by_id = {r.enrollment_id: r for r in result.results}
    assert [r.enrollment_id for r in result.results] == ["a", "gone", "missing", "c", "d"]
    assert by_id["a"].ok and by_id["c"].ok
    assert by_id["gone"].error_code == "Enrollment.NotTransferable"
    assert by_id["missing"].error_code == "Enrollment.NotFound"
    assert by_id["d"].error_code == "Enrollment.CapacityExceeded"
    assert result.moved_count == 2 and result.failed_count == 3
    # The refused rows were left exactly where they were.
    assert enrollments.rows["gone"].session_id == "sess-1"
    assert enrollments.rows["d"].session_id == "sess-1"
    assert sessions.reserved == {"sess-1": 1, "sess-2": 2}


@pytest.mark.asyncio
async def test_bulk_transfer_moves_a_repeated_id_once() -> None:
    enrollments = FakeEnrollments(rows={"a": _row("a")})
    billing = RecordingMoveBillingSync()

    result = await _bulk(
        enrollments, CappedSessions(reserved={"sess-1": 1}), FakeEnrollmentEvents(), billing
    ).execute(BulkTransferEnrollmentsCommand(enrollment_ids=["a", "a"], target_session_id="sess-2"))

    assert [r.enrollment_id for r in result.results] == ["a"]
    assert len(billing.calls) == 1


class StaleReadEnrollments(FakeEnrollments):
    """The row was moved by a concurrent request after this one read it."""

    async def get(self, enrollment_id: str) -> Enrollment | None:
        row = self.rows.get(enrollment_id)
        return row.model_copy(update={"session_id": "sess-1"}) if row else None


@pytest.mark.asyncio
async def test_a_row_moved_by_a_concurrent_request_is_refused_and_its_seat_released() -> None:
    enrollments = StaleReadEnrollments(
        rows={"a": _row("a").model_copy(update={"session_id": "sess-3"})}
    )
    sessions = CappedSessions(reserved={"sess-1": 1, "sess-2": 0})
    events = FakeEnrollmentEvents()

    result = await _bulk(enrollments, sessions, events, RecordingMoveBillingSync()).execute(
        BulkTransferEnrollmentsCommand(enrollment_ids=["a"], target_session_id="sess-2")
    )

    assert result.results[0].error_code == "Enrollment.MovedConcurrently"
    assert enrollments.rows["a"].session_id == "sess-3"
    # The target seat reserved for the losing move went back; no event recorded.
    assert sessions.reserved == {"sess-1": 1, "sess-2": 0}
    assert events.rows == []


class ExplodingEvents(FakeEnrollmentEvents):
    async def record(self, event) -> None:
        raise RuntimeError("event store down")


@pytest.mark.asyncio
async def test_an_unexpected_failure_after_the_move_does_not_claim_the_row_stayed() -> None:
    enrollments = FakeEnrollments(rows={"a": _row("a")})

    result = await _bulk(
        enrollments,
        CappedSessions(reserved={"sess-1": 1}),
        ExplodingEvents(),
        RecordingMoveBillingSync(),
    ).execute(BulkTransferEnrollmentsCommand(enrollment_ids=["a"], target_session_id="sess-2"))

    row = result.results[0]
    assert row.error_code == "Enrollment.TransferFailed"
    assert enrollments.rows["a"].session_id == "sess-2"  # it did move
    assert "check where they are" in (row.message or "")
    assert "stay" not in (row.message or "").lower()
