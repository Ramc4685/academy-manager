"""Issue #704 (second-review correction): CoachAddStudentToRoster must route
through SeatBroker exactly like the admin roster-add path does.

Before this fix, ``CoachAddStudentToRoster.execute`` built a fresh
``EditRosterAdd`` on every call — never brokered, and invisible to
``tests/structural/test_seat_broker_wiring.py`` because that construction
happened outside ``composition/`` entirely (see
``contexts/enrollment/application/use_cases/coach_roster_writes.py``). A
coach adding a student to a class that was full only because a held
enrollment occupied the seat got "session full" instead of a reclaim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.seat_broker import SeatBroker
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import EditRosterAdd
from backend.v2.contexts.enrollment.application.use_cases.coach_roster_writes import (
    CoachAddStudentToRoster,
    CoachAddStudentToRosterCommand,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded
from backend.v2.tests.fixtures.enrollment_fakes import (
    FakeDeparturePolicyRepo,
    FakeEnrollmentWriter,
    FakeHoldRepository,
    FakeSessionWriter,
    make_enrollment,
    make_session,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@dataclass
class _FakeStudentWriter:
    ensured: list[Any] = field(default_factory=list)

    async def ensure_exists(self, student: Any) -> bool:
        self.ensured.append(student)
        return True


class _AlwaysAssigned:
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return True


def _uc(
    *, sessions: FakeSessionWriter, enrollments: FakeEnrollmentWriter
) -> tuple[CoachAddStudentToRoster, EditRosterAdd]:
    edit_roster_add = EditRosterAdd(
        sessions=sessions,
        enrollments=enrollments,
        students=_FakeStudentWriter(),
        academy_id="acad",
        clock=lambda: NOW,
    )
    return (
        CoachAddStudentToRoster(
            edit_roster_add=edit_roster_add,
            assigned_sessions=_AlwaysAssigned(),
        ),
        edit_roster_add,
    )


@pytest.mark.asyncio
async def test_coach_add_reclaims_a_held_seat_instead_of_reporting_the_session_full() -> None:
    """The live gap #704's second review found: a class full only because a
    held enrollment occupies the seat must reclaim through SeatBroker, not
    raise CapacityExceeded the way a direct, unbrokered
    ``try_reserve_seat`` call did."""
    session = make_session("sess-1", capacity=1)
    sessions = FakeSessionWriter(sessions={"sess-1": session})
    sessions.reserved_seats["sess-1"] = 1
    victim = make_enrollment("enr-held", session_id="sess-1", student_id="stu-held", status="held")
    enrollments = FakeEnrollmentWriter(rows={"enr-held": victim})
    holds = FakeHoldRepository(enrollments=enrollments)
    seat_broker = SeatBroker(
        sessions=sessions,
        holds=holds,
        departure_policy=FakeDeparturePolicyRepo(),
    )

    uc, _delegate = _uc(sessions=sessions, enrollments=enrollments)
    uc.set_seat_broker(seat_broker)

    enrollment = await uc.execute(
        CoachAddStudentToRosterCommand(
            coach_id="coach-1",
            session_id="sess-1",
            student_id="stu-new",
            parent_id="par-1",
            full_name="Kid New",
        )
    )

    assert enrollment.status == "active"
    assert holds.claimed_ids == ["enr-held"]
    assert enrollments.rows["enr-held"].status == "dropped"


@pytest.mark.asyncio
async def test_coach_add_without_a_seat_broker_still_reports_the_session_full() -> None:
    """No regression for the unwired (test/legacy) path: without a broker,
    a full session still raises CapacityExceeded — reclaim is additive."""
    session = make_session("sess-1", capacity=1)
    sessions = FakeSessionWriter(sessions={"sess-1": session})
    sessions.reserved_seats["sess-1"] = 1
    enrollments = FakeEnrollmentWriter(
        rows={"enr-other": make_enrollment("enr-other", session_id="sess-1", status="active")}
    )

    uc, _delegate = _uc(sessions=sessions, enrollments=enrollments)

    with pytest.raises(CapacityExceeded):
        await uc.execute(
            CoachAddStudentToRosterCommand(
                coach_id="coach-1",
                session_id="sess-1",
                student_id="stu-new",
                parent_id="par-1",
                full_name="Kid New",
            )
        )


@pytest.mark.asyncio
async def test_set_seat_broker_delegates_to_the_underlying_edit_roster_add() -> None:
    """CoachAddStudentToRoster.set_seat_broker is the escape hatch production
    wiring uses (main.py) — it must reach the wrapped EditRosterAdd, the
    object that actually calls try_reserve_seat."""
    sessions = FakeSessionWriter()
    enrollments = FakeEnrollmentWriter()
    uc, delegate = _uc(sessions=sessions, enrollments=enrollments)
    seat_broker = SeatBroker(
        sessions=sessions,
        holds=FakeHoldRepository(enrollments=enrollments),
        departure_policy=FakeDeparturePolicyRepo(),
    )

    uc.set_seat_broker(seat_broker)

    assert delegate._seat_broker is seat_broker
