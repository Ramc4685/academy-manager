"""Use-case tests for CorrectAttendance (#517).

Coach corrections are allowed inside the 48h grace window on an occurrence
they are assigned to; admin corrections are allowed any time. Every real
correction stamps the audit trail and emits Coaching.AttendanceCorrected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
    CorrectAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    AttendanceNotFound,
    CorrectionWindowExpired,
    SessionNotAssigned,
)
from backend.v2.contexts.coaching.domain.models import Attendance

MARKED_AT = datetime(2026, 5, 16, 9, 30, tzinfo=UTC)


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list[Attendance] = []
        self.updated: list[Attendance] = []

    async def save(self, attendance: Attendance) -> None:
        self.saved.append(attendance)

    async def update_status(self, attendance: Attendance) -> None:
        self.updated.append(attendance)
        self.saved = [
            attendance if a.attendance_id == attendance.attendance_id else a for a in self.saved
        ]

    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None:
        for a in self.saved:
            if a.occurrence_id == occurrence_id and a.student_id == student_id:
                return a
        return None

    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None:
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeOccurrenceLookup:
    def __init__(self, *, assigned: bool = True, found: bool = True) -> None:
        self.assigned = assigned
        self.found = found

    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        if not self.found:
            return None
        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id="sess-1",
            starts_at=MARKED_AT,
            status="scheduled",
            scheduled_coach_id="coach-1" if self.assigned else "other-coach",
        )


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list[Any] = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)


def _mark(status: str = "present") -> Attendance:
    return Attendance(
        attendance_id="mut-1",
        academy_id="test-academy",
        occurrence_id="occ-1",
        session_id="sess-1",
        student_id="st1",
        marked_by="coach-1",
        marked_at=MARKED_AT,
        status=status,  # type: ignore[arg-type]
    )


def _cmd(status: str = "absent", reason: str | None = "mis-tap") -> CorrectAttendanceCommand:
    return CorrectAttendanceCommand(
        occurrence_id="occ-1",
        student_id="st1",
        status=status,  # type: ignore[arg-type]
        reason=reason,
    )


def _build(*, now: datetime, repo=None, occurrences=None, outbox=None) -> CorrectAttendance:
    return CorrectAttendance(
        attendance_repo=repo or FakeAttendanceRepo(),
        occurrence_lookup=occurrences or FakeOccurrenceLookup(),
        outbox=outbox or FakeOutbox(),
        academy_id=lambda: "test-academy",
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_coach_corrects_within_window_with_audit_trail_and_event() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    outbox = FakeOutbox()
    now = MARKED_AT + timedelta(hours=2)
    uc = _build(now=now, repo=repo, outbox=outbox)

    result = await uc.execute(_cmd("absent"), actor_id="coach-1", actor_role="coach")

    assert result.status == "absent"
    assert result.previous_status == "present"
    assert result.corrected_by == "coach-1"
    assert result.corrected_at == now
    assert len(repo.updated) == 1
    row = repo.updated[0]
    assert row.status == "absent"
    assert row.previous_status == "present"
    assert row.corrected_by == "coach-1"
    assert row.correction_reason == "mis-tap"
    assert len(outbox.appended) == 1
    event = outbox.appended[0]
    assert event.name == "Coaching.AttendanceCorrected"
    assert event.payload.previous_status == "present"
    assert event.payload.status == "absent"
    assert event.payload.actor_role == "coach"


@pytest.mark.asyncio
async def test_coach_outside_window_rejected() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    uc = _build(now=MARKED_AT + timedelta(hours=49), repo=repo)
    with pytest.raises(CorrectionWindowExpired):
        await uc.execute(_cmd("absent"), actor_id="coach-1", actor_role="coach")


@pytest.mark.asyncio
async def test_admin_corrects_after_window() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    outbox = FakeOutbox()
    now = MARKED_AT + timedelta(days=45)
    uc = _build(now=now, repo=repo, outbox=outbox)

    result = await uc.execute(_cmd("late"), actor_id="admin-1", actor_role="admin")

    assert result.status == "late"
    assert result.previous_status == "present"
    assert result.corrected_by == "admin-1"
    assert outbox.appended[0].payload.actor_role == "admin"


@pytest.mark.asyncio
async def test_unassigned_coach_rejected() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    uc = _build(
        now=MARKED_AT + timedelta(hours=1),
        repo=repo,
        occurrences=FakeOccurrenceLookup(assigned=False),
    )
    with pytest.raises(SessionNotAssigned):
        await uc.execute(_cmd("absent"), actor_id="coach-1", actor_role="coach")


@pytest.mark.asyncio
async def test_missing_mark_raises_not_found() -> None:
    uc = _build(now=MARKED_AT)
    with pytest.raises(AttendanceNotFound):
        await uc.execute(_cmd("absent"), actor_id="admin-1", actor_role="admin")


@pytest.mark.asyncio
async def test_same_status_is_a_noop() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    outbox = FakeOutbox()
    uc = _build(now=MARKED_AT + timedelta(hours=1), repo=repo, outbox=outbox)

    result = await uc.execute(_cmd("present", reason=None), actor_id="coach-1", actor_role="coach")

    assert result.status == "present"
    assert result.previous_status is None
    assert repo.updated == []
    assert outbox.appended == []


@pytest.mark.asyncio
async def test_second_correction_keeps_latest_previous_status() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    outbox = FakeOutbox()
    uc = _build(now=MARKED_AT + timedelta(hours=1), repo=repo, outbox=outbox)

    await uc.execute(_cmd("absent"), actor_id="coach-1", actor_role="coach")
    result = await uc.execute(_cmd("late"), actor_id="admin-1", actor_role="admin")

    assert result.previous_status == "absent"
    assert result.corrected_by == "admin-1"
    assert len(outbox.appended) == 2
