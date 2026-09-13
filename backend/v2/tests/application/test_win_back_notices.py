"""Issue #778: win-back at 30/60/90 days after departure.

Fakes mirror the shape of the real ports closely enough to exercise the
use case's actual decision logic (milestone due-ness, re-enrollment
cancellation, owes-money suppression) without touching Mongo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.win_back import (
    SendWinBackNotices,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student

ACADEMY_ID = "acad-1"


def _dropped_event(student_id: str, *, effective_at: datetime) -> EnrollmentLifecycleEvent:
    return EnrollmentLifecycleEvent(
        event_id=f"evt-{student_id}",
        academy_id=ACADEMY_ID,
        event_type="dropped",
        enrollment_id=f"enr-{student_id}",
        student_id=student_id,
        effective_at=effective_at,
        occurred_at=effective_at,
    )


def _student(student_id: str, parent_id: str = "parent-1") -> Student:
    return Student(
        student_id=student_id,
        academy_id=ACADEMY_ID,
        parent_id=parent_id,
        full_name="Test Student",
    )


class FakeEnrollmentEventRepository:
    def __init__(self, events: list[EnrollmentLifecycleEvent]) -> None:
        self._events = events

    async def record(self, event) -> None:  # pragma: no cover - unused here
        self._events.append(event)

    async def list_for_enrollment(self, enrollment_id: str):  # pragma: no cover - unused
        return [e for e in self._events if e.enrollment_id == enrollment_id]

    async def list_in_range(self, *, start, end, event_types):
        return [
            e for e in self._events if e.event_type in event_types and start <= e.occurred_at < end
        ]


class FakeEnrollmentQuery:
    def __init__(self, active_by_student: dict[str, list[Enrollment]] | None = None) -> None:
        self._active_by_student = active_by_student or {}

    async def active_for_student(self, student_id: str) -> list[Enrollment]:
        return self._active_by_student.get(student_id, [])


class FakeStudentQuery:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._by_id[sid] for sid in student_ids if sid in self._by_id]

    async def get_for_parent(self, parent_id, student_id):  # pragma: no cover - unused
        return self._by_id.get(student_id)


class FakeWinBackSendRepository:
    """In-memory stand-in for the unique-index-backed Mongo claim."""

    def __init__(self) -> None:
        self._claimed: set[tuple[str, str, str]] = set()
        self.sent_ids: list[str] = []

    async def try_claim(self, *, academy_id: str, student_id: str, milestone_key: str):
        key = (academy_id, student_id, milestone_key)
        if key in self._claimed:
            return None
        self._claimed.add(key)
        send_id = f"send-{student_id}-{milestone_key}"
        return {"send_id": send_id}

    async def mark_sent(self, send_id: str) -> None:
        self.sent_ids.append(send_id)


class FakeFamilyBalanceLookup:
    def __init__(self, owes_by_parent: dict[str, int] | None = None) -> None:
        self._owes_by_parent = owes_by_parent or {}

    async def outstanding_cents_for_parent(self, parent_id: str) -> int:
        return self._owes_by_parent.get(parent_id, 0)


class FakeWinBackNotifier:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def win_back(self, *, student_id, parent_id, milestone_days, dropped_at) -> None:
        self.sent.append(
            {
                "student_id": student_id,
                "parent_id": parent_id,
                "milestone_days": milestone_days,
                "dropped_at": dropped_at,
            }
        )


def _build(
    *,
    events: list[EnrollmentLifecycleEvent],
    students: list[Student],
    active_by_student: dict[str, list[Enrollment]] | None = None,
    owes_by_parent: dict[str, int] | None = None,
    send_repo: FakeWinBackSendRepository | None = None,
    now: datetime,
):
    send_repo = send_repo or FakeWinBackSendRepository()
    notifier = FakeWinBackNotifier()
    use_case = SendWinBackNotices(
        enrollment_events=FakeEnrollmentEventRepository(events),
        enrollments=FakeEnrollmentQuery(active_by_student),
        students=FakeStudentQuery(students),
        send_repo=send_repo,
        balance_lookup=FakeFamilyBalanceLookup(owes_by_parent),
        notifier=notifier,
        clock=lambda: now,
    )
    return use_case, send_repo, notifier


@pytest.mark.asyncio
async def test_sends_exactly_one_notice_at_30_day_milestone():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    dropped_at = now - timedelta(days=30)
    event = _dropped_event("stu-1", effective_at=dropped_at)
    student = _student("stu-1")
    use_case, send_repo, notifier = _build(events=[event], students=[student], now=now)

    sent = await use_case.execute(academy_id=ACADEMY_ID)

    assert sent == 1
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["milestone_days"] == 30
    assert (ACADEMY_ID, "stu-1", "30") in send_repo._claimed


@pytest.mark.asyncio
async def test_second_tick_same_day_is_idempotent_noop():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    dropped_at = now - timedelta(days=30)
    event = _dropped_event("stu-1", effective_at=dropped_at)
    student = _student("stu-1")
    send_repo = FakeWinBackSendRepository()
    use_case, send_repo, notifier = _build(
        events=[event], students=[student], send_repo=send_repo, now=now
    )

    first = await use_case.execute(academy_id=ACADEMY_ID)
    second = await use_case.execute(academy_id=ACADEMY_ID)

    assert first == 1
    assert second == 0
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_re_enrolled_student_is_skipped_and_no_claim_written():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    dropped_at = now - timedelta(days=30)
    event = _dropped_event("stu-1", effective_at=dropped_at)
    student = _student("stu-1")
    active_enrollment = Enrollment(
        enrollment_id="enr-new",
        academy_id=ACADEMY_ID,
        session_id="sess-1",
        student_id="stu-1",
        status="active",
    )
    use_case, send_repo, notifier = _build(
        events=[event],
        students=[student],
        active_by_student={"stu-1": [active_enrollment]},
        now=now,
    )

    sent = await use_case.execute(academy_id=ACADEMY_ID)

    assert sent == 0
    assert notifier.sent == []
    assert send_repo._claimed == set()


@pytest.mark.asyncio
async def test_family_that_owes_money_is_suppressed():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    dropped_at = now - timedelta(days=30)
    event = _dropped_event("stu-1", effective_at=dropped_at)
    student = _student("stu-1", parent_id="parent-owing")
    use_case, send_repo, notifier = _build(
        events=[event],
        students=[student],
        owes_by_parent={"parent-owing": 500},
        now=now,
    )

    sent = await use_case.execute(academy_id=ACADEMY_ID)

    assert sent == 0
    assert notifier.sent == []
    assert send_repo._claimed == set()


@pytest.mark.asyncio
async def test_no_notifier_configured_is_a_safe_noop():
    now = datetime(2026, 9, 13, tzinfo=UTC)
    dropped_at = now - timedelta(days=30)
    event = _dropped_event("stu-1", effective_at=dropped_at)
    student = _student("stu-1")
    send_repo = FakeWinBackSendRepository()
    use_case = SendWinBackNotices(
        enrollment_events=FakeEnrollmentEventRepository([event]),
        enrollments=FakeEnrollmentQuery(),
        students=FakeStudentQuery([student]),
        send_repo=send_repo,
        balance_lookup=FakeFamilyBalanceLookup(),
        notifier=None,
        clock=lambda: now,
    )

    sent = await use_case.execute(academy_id=ACADEMY_ID)

    assert sent == 0
