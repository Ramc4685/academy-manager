"""Use-case tests for VoidAttendance (#554).

Owner decision 2026-09-12: an admin may void an attendance mark at any
time, a reason is required, and the void is audited. A voided mark counts
as unmarked everywhere downstream, so the row keeps its history rather
than being deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.v2.contexts.coaching.application.use_cases.void_attendance import (
    VoidAttendance,
    VoidAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import AttendanceNotFound
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.tests.application.test_correct_attendance import (
    MARKED_AT,
    FakeAttendanceRepo,
    FakeOutbox,
)


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


def _build(*, now: datetime, repo=None, outbox=None) -> VoidAttendance:
    return VoidAttendance(
        attendance_repo=repo or FakeAttendanceRepo(),
        outbox=outbox or FakeOutbox(),
        academy_id=lambda: "test-academy",
        clock=lambda: now,
    )


def test_voided_is_a_valid_attendance_status() -> None:
    assert _mark("voided").status == "voided"


@pytest.mark.asyncio
async def test_admin_can_void_at_any_time_with_reason() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("present"))
    outbox = FakeOutbox()
    now = MARKED_AT + timedelta(days=90)
    uc = _build(now=now, repo=repo, outbox=outbox)

    result = await uc.execute(
        VoidAttendanceCommand(
            occurrence_id="occ-1", student_id="st1", reason="marked on the wrong class"
        ),
        actor_id="admin-1",
    )

    assert result.status == "voided"
    assert result.previous_status == "present"
    assert result.corrected_by == "admin-1"
    assert result.corrected_at == now
    assert len(repo.updated) == 1
    row = repo.updated[0]
    assert row.status == "voided"
    assert row.previous_status == "present"
    assert row.correction_reason == "marked on the wrong class"
    assert len(outbox.appended) == 1
    event = outbox.appended[0]
    assert event.name == "Coaching.AttendanceVoided"
    assert event.payload.previous_status == "present"
    assert event.payload.voided_by == "admin-1"
    assert event.payload.reason == "marked on the wrong class"


@pytest.mark.asyncio
async def test_void_requires_a_non_empty_reason() -> None:
    with pytest.raises(ValidationError):
        VoidAttendanceCommand(occurrence_id="occ-1", student_id="st1", reason="   ")
    with pytest.raises(ValidationError):
        VoidAttendanceCommand(occurrence_id="occ-1", student_id="st1")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_void_missing_mark_raises_attendance_not_found() -> None:
    uc = _build(now=MARKED_AT)
    with pytest.raises(AttendanceNotFound):
        await uc.execute(
            VoidAttendanceCommand(occurrence_id="occ-1", student_id="st1", reason="mis-tap"),
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_voiding_an_already_voided_mark_is_a_noop() -> None:
    repo = FakeAttendanceRepo()
    repo.saved.append(_mark("voided"))
    outbox = FakeOutbox()
    uc = _build(now=MARKED_AT + timedelta(hours=1), repo=repo, outbox=outbox)

    result = await uc.execute(
        VoidAttendanceCommand(occurrence_id="occ-1", student_id="st1", reason="again"),
        actor_id="admin-1",
    )

    assert result.status == "voided"
    assert repo.updated == []
    assert outbox.appended == []


def test_downstream_readers_never_count_a_voided_mark() -> None:
    """A voided mark is unmarked for attendance rate and payroll (#554).

    Both readers enumerate the statuses they count, so the guarantee is
    that ``voided`` is absent from those lists.
    """
    from backend.v2.contexts.billing.application.use_cases.finance import ATTENDED_STATUSES
    from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
        ATTENDANCE_RATE_COUNTED_STATUSES,
        ATTENDANCE_RATE_PRESENT_STATUSES,
    )

    assert "voided" not in ATTENDED_STATUSES
    assert "voided" not in ATTENDANCE_RATE_COUNTED_STATUSES
    assert "voided" not in ATTENDANCE_RATE_PRESENT_STATUSES


def test_now_defaults_to_utc_clock() -> None:
    uc = VoidAttendance(
        attendance_repo=FakeAttendanceRepo(),
        outbox=FakeOutbox(),
        academy_id=lambda: "test-academy",
    )
    assert uc._now().tzinfo is UTC
