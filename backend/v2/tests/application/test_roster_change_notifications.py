"""Enrollment lifecycle notifications — the port contract (issue #612).

Two things are pinned here, once per trigger:

* the notifier is called exactly once, with the change kind that trigger owns,
  after the write has settled; and
* a notifier that *raises* changes nothing about the enrollment. A mail
  provider outage must never turn into a failed cancellation, a phantom
  "add failed" for an add that succeeded, or a lost seat.

The second half is the one that matters in production and the one a refactor
can silently break, so every trigger gets its own raising-notifier case rather
than a single representative one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelEnrollmentCommand,
    EditRosterAdd,
    EditRosterAddCommand,
    TransferEnrollment,
    TransferEnrollmentCommand,
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry

ACADEMY = "acad-1"


def _session(session_id: str = "sess-1", *, capacity: int = 10) -> Session:
    return Session(
        session_id=session_id,
        academy_id=ACADEMY,
        coach_id="coach-1",
        title="Beginner Badminton",
        location="Court 1",
        start_at=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
        capacity=capacity,
    )


def _enrollment(enrollment_id: str = "enr-1", session_id: str = "sess-1") -> Enrollment:
    return Enrollment(
        enrollment_id=enrollment_id,
        academy_id=ACADEMY,
        session_id=session_id,
        student_id="st-1",
        status="active",
    )


@dataclass
class RecordingNotifier:
    """A ``RosterChangeNotifier`` that records, or blows up on purpose."""

    raises: BaseException | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def roster_changed(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises


@dataclass
class FakeSessions:
    sessions: dict[str, Session] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)
    released: list[str] = field(default_factory=list)

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None or self.reserved.get(session_id, 0) >= session.capacity:
            return False
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.released.append(session_id)
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)


@dataclass
class FakeEnrollments:
    rows: dict[str, Enrollment] = field(default_factory=dict)

    async def create(self, enrollment: Enrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def update_status(self, enrollment_id: str, status: str) -> None:
        row = self.rows[enrollment_id]
        self.rows[enrollment_id] = row.model_copy(update={"status": status})

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        row = self.rows[enrollment_id]
        self.rows[enrollment_id] = row.model_copy(update={"session_id": session_id})

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.session_id == session_id and row.student_id == student_id
            ),
            None,
        )

    async def count_active_for_session(self, session_id: str) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.session_id == session_id and row.status == "active"
        )


@dataclass
class FakeStudents:
    rows: dict[str, Student] = field(default_factory=dict)

    async def upsert(self, student: Student) -> None:
        self.rows[student.student_id] = student

    async def ensure_exists(self, student: Student) -> bool:
        if student.student_id in self.rows:
            return False
        self.rows[student.student_id] = student
        return True


@dataclass
class FakeOutbox:
    events: list[Any] = field(default_factory=list)

    async def append(self, event: Any, *, session: Any = None) -> None:
        self.events.append(event)

    async def pull_unprocessed(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    async def mark_processed(self, event_id: str) -> None:  # pragma: no cover - unused
        return None


@dataclass
class FakeWaitlist:
    entries: list[WaitlistEntry] = field(default_factory=list)
    statuses: dict[str, str] = field(default_factory=dict)

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        return next(
            (e for e in self.entries if e.session_id == session_id and e.status == "waiting"),
            None,
        )

    async def update_status(self, waitlist_id: str, status: str) -> None:
        self.statuses[waitlist_id] = status


BOOM = RuntimeError("resend is down")


# --- admin add to roster ------------------------------------------------


def _edit_roster_add(notifier: RecordingNotifier) -> tuple[EditRosterAdd, FakeEnrollments]:
    sessions = FakeSessions(sessions={"sess-1": _session()})
    enrollments = FakeEnrollments()
    return (
        EditRosterAdd(
            sessions=sessions,  # type: ignore[arg-type]
            enrollments=enrollments,  # type: ignore[arg-type]
            students=FakeStudents(),  # type: ignore[arg-type]
            academy_id=ACADEMY,
            roster_notifier=notifier,  # type: ignore[arg-type]
        ),
        enrollments,
    )


@pytest.mark.asyncio
async def test_roster_add_notifies_once_with_added() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _edit_roster_add(notifier)

    await use_case.execute(
        EditRosterAddCommand(
            session_id="sess-1",
            student_id="st-1",
            parent_id="par-1",
            full_name="Alice Nguyen",
            actor_id="admin-1",
        )
    )

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["change"] == "added"
    assert call["session_id"] == "sess-1"
    assert call["student_name"] == "Alice Nguyen"
    # The actor rides along so the adapter can leave them off the audience.
    assert call["actor_id"] == "admin-1"


@pytest.mark.asyncio
async def test_a_raising_notifier_still_leaves_the_student_on_the_roster() -> None:
    notifier = RecordingNotifier(raises=BOOM)
    use_case, enrollments = _edit_roster_add(notifier)

    enrollment = await use_case.execute(
        EditRosterAddCommand(
            session_id="sess-1",
            student_id="st-1",
            parent_id="par-1",
            full_name="Alice Nguyen",
        )
    )

    assert enrollments.rows[enrollment.enrollment_id].status == "active"


# --- cancel -------------------------------------------------------------


def _cancel(notifier: RecordingNotifier) -> tuple[CancelEnrollment, FakeEnrollments]:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    return (
        CancelEnrollment(
            enrollments=enrollments,  # type: ignore[arg-type]
            sessions=FakeSessions(sessions={"sess-1": _session()}),  # type: ignore[arg-type]
            outbox=FakeOutbox(),  # type: ignore[arg-type]
            academy_id=ACADEMY,
            roster_notifier=notifier,  # type: ignore[arg-type]
        ),
        enrollments,
    )


@pytest.mark.asyncio
async def test_cancel_notifies_once_with_cancelled() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _cancel(notifier)

    await use_case.execute(CancelEnrollmentCommand(enrollment_id="enr-1", actor_id="admin-1"))

    assert [c["change"] for c in notifier.calls] == ["cancelled"]
    assert notifier.calls[0]["enrollment_id"] == "enr-1"


@pytest.mark.asyncio
async def test_cancel_survives_a_raising_notifier() -> None:
    notifier = RecordingNotifier(raises=BOOM)
    use_case, enrollments = _cancel(notifier)

    await use_case.execute(CancelEnrollmentCommand(enrollment_id="enr-1"))

    assert enrollments.rows["enr-1"].status == "cancelled"


@pytest.mark.asyncio
async def test_an_already_cancelled_enrollment_notifies_nobody() -> None:
    """The early return is the dedupe: a double-clicked cancel sends one alert."""
    notifier = RecordingNotifier()
    use_case, _enrollments = _cancel(notifier)

    await use_case.execute(CancelEnrollmentCommand(enrollment_id="enr-1"))
    await use_case.execute(CancelEnrollmentCommand(enrollment_id="enr-1"))

    assert len(notifier.calls) == 1


# --- transfer -----------------------------------------------------------


def _transfer(notifier: RecordingNotifier) -> tuple[TransferEnrollment, FakeEnrollments]:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    sessions = FakeSessions(sessions={"sess-1": _session(), "sess-2": _session("sess-2")})
    return (
        TransferEnrollment(
            enrollments=enrollments,  # type: ignore[arg-type]
            sessions=sessions,  # type: ignore[arg-type]
            roster_notifier=notifier,  # type: ignore[arg-type]
        ),
        enrollments,
    )


@pytest.mark.asyncio
async def test_transfer_notifies_with_both_sides() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _transfer(notifier)

    await use_case.execute(
        TransferEnrollmentCommand(
            enrollment_id="enr-1", target_session_id="sess-2", actor_id="admin-1"
        )
    )

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["change"] == "moved"
    # One call, both rosters: the adapter tells the coach who lost the student
    # as well as the one who gained them.
    assert call["from_session_id"] == "sess-1"
    assert call["to_session_id"] == "sess-2"
    assert call["session_id"] == "sess-2"


@pytest.mark.asyncio
async def test_transfer_survives_a_raising_notifier() -> None:
    notifier = RecordingNotifier(raises=BOOM)
    use_case, enrollments = _transfer(notifier)

    await use_case.execute(
        TransferEnrollmentCommand(enrollment_id="enr-1", target_session_id="sess-2")
    )

    assert enrollments.rows["enr-1"].session_id == "sess-2"


@pytest.mark.asyncio
async def test_a_transfer_to_the_same_session_notifies_nobody() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _transfer(notifier)

    await use_case.execute(
        TransferEnrollmentCommand(enrollment_id="enr-1", target_session_id="sess-1")
    )

    assert notifier.calls == []


# --- withdraw -----------------------------------------------------------


def _withdraw(notifier: RecordingNotifier) -> tuple[WithdrawEnrollment, FakeEnrollments]:
    enrollments = FakeEnrollments(rows={"enr-1": _enrollment()})
    return (
        WithdrawEnrollment(
            enrollments=enrollments,  # type: ignore[arg-type]
            roster_notifier=notifier,  # type: ignore[arg-type]
        ),
        enrollments,
    )


@pytest.mark.asyncio
async def test_withdraw_notifies_once_with_withdrawn() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _withdraw(notifier)

    await use_case.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=datetime(2026, 9, 1, tzinfo=UTC),
            actor_id="admin-1",
            reason="moving away",
        )
    )

    assert [c["change"] for c in notifier.calls] == ["withdrawn"]


@pytest.mark.asyncio
async def test_withdraw_survives_a_raising_notifier() -> None:
    notifier = RecordingNotifier(raises=BOOM)
    use_case, enrollments = _withdraw(notifier)

    await use_case.execute(
        WithdrawEnrollmentCommand(
            enrollment_id="enr-1",
            effective_at=datetime(2026, 9, 1, tzinfo=UTC),
            actor_id="admin-1",
            reason="moving away",
        )
    )

    assert enrollments.rows["enr-1"].status == "withdrawn"


# --- waitlist promotion -------------------------------------------------


def _promote(notifier: RecordingNotifier) -> tuple[PromoteFromWaitlist, FakeWaitlist]:
    waitlist = FakeWaitlist(
        entries=[
            WaitlistEntry(
                waitlist_id="wl-1",
                academy_id=ACADEMY,
                session_id="sess-1",
                student_id="st-1",
                parent_id="par-1",
                joined_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ]
    )
    return (
        PromoteFromWaitlist(
            waitlist=waitlist,  # type: ignore[arg-type]
            sessions=FakeSessions(sessions={"sess-1": _session()}),  # type: ignore[arg-type]
            enrollments=FakeEnrollments(),  # type: ignore[arg-type]
            outbox=FakeOutbox(),  # type: ignore[arg-type]
            academy_id=lambda: ACADEMY,
            roster_notifier=notifier,  # type: ignore[arg-type]
        ),
        waitlist,
    )


@pytest.mark.asyncio
async def test_promotion_notifies_with_the_parent_so_the_family_is_told() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _promote(notifier)

    await use_case.execute("sess-1", actor_id="admin-1")

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["change"] == "promoted"
    # Phase 2 hangs off this field: without the parent id the family never
    # learns a seat opened.
    assert call["parent_user_id"] == "par-1"


@pytest.mark.asyncio
async def test_promotion_survives_a_raising_notifier() -> None:
    notifier = RecordingNotifier(raises=BOOM)
    use_case, waitlist = _promote(notifier)

    result = await use_case.execute("sess-1")

    assert result == "wl-1"
    assert waitlist.statuses["wl-1"] == "promoted"


@pytest.mark.asyncio
async def test_an_empty_waitlist_notifies_nobody() -> None:
    notifier = RecordingNotifier()
    use_case, _ = _promote(notifier)

    assert await use_case.execute("sess-2") is None
    assert notifier.calls == []
