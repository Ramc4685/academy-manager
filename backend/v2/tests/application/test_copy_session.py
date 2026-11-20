"""A0-8: Copy class creates a new class from an existing one.

The new class goes through ``CreateSession`` (duplicate-series and timezone
rules) and the optional roster copy through ``EditRosterAdd`` (seat checks,
lifecycle event, notices), so neither path can drift from the normal one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CreateSession,
    EditRosterAdd,
)
from backend.v2.contexts.enrollment.application.use_cases.copy_session import (
    CopySession,
    CopySessionCommand,
)
from backend.v2.contexts.enrollment.domain.errors import (
    CopyRosterRefused,
    DuplicateSessionSeries,
    SessionNotFound,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student

SOURCE = Session(
    session_id="src",
    academy_id="acad",
    coach_id="coach-1",
    title="Tuesday Beginners",
    location="Court 1",
    start_at=datetime(2026, 11, 24, 0, 0, tzinfo=UTC),
    end_at=datetime(2026, 11, 24, 1, 0, tzinfo=UTC),
    capacity=2,
    amount_cents=12000,
    days_of_week=["Tue"],
    start_time="18:00",
    end_time="19:00",
    timezone="America/Chicago",
    assistant_coach_ids=("coach-2",),
    what_to_bring="Racket and water",
)


@dataclass
class FakeSessions:
    rows: dict[str, Session] = field(default_factory=lambda: {"src": SOURCE})
    reserved: dict[str, int] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)

    async def create(self, session: Session) -> None:
        self.rows[session.session_id] = session

    async def find_duplicate_recurring_series(self, **kw: object) -> Session | None:
        for row in self.rows.values():
            if (
                row.title.lower() == kw["title"]
                and row.days_of_week == kw["days_of_week"]
                and row.start_time == kw["start_time"]
            ):
                return row
        return None

    async def try_reserve_seat(self, session_id: str) -> bool:
        used = self.reserved.get(session_id, 0)
        if used >= self.rows[session_id].capacity:
            return False
        self.reserved[session_id] = used + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)


@dataclass
class FakeEnrollments:
    rows: list[Enrollment] = field(default_factory=list)

    async def create(self, enrollment: Enrollment) -> None:
        self.rows.append(enrollment)

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (e for e in self.rows if e.session_id == session_id and e.student_id == student_id),
            None,
        )

    async def count_active_for_session(self, session_id: str) -> int:
        return len(await self.active_for_session(session_id))

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self.rows if e.session_id == session_id and e.status == "active"]


@dataclass
class FakeStudents:
    rows: dict[str, Student]

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self.rows[s] for s in student_ids if s in self.rows]

    async def ensure_exists(self, student: Student) -> bool:
        return False


def _enrolled(student_id: str, status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id=f"e-{student_id}",
        academy_id="acad",
        session_id="src",
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
    )


def _student(student_id: str, name: str) -> Student:
    return Student(
        student_id=student_id, academy_id="acad", parent_id=f"p-{student_id}", full_name=name
    )


def _use_case(sessions: FakeSessions, enrollments: FakeEnrollments, students: FakeStudents):
    async def _tz(_academy_id: str) -> str:
        return "America/Chicago"

    return CopySession(
        sessions=sessions,
        create_session=CreateSession(
            sessions=sessions, academy_id="acad", get_academy_timezone=_tz
        ),
        enrollments=enrollments,
        students=students,
        roster_add=EditRosterAdd(
            sessions=sessions, enrollments=enrollments, students=students, academy_id="acad"
        ),
    )


@pytest.mark.asyncio
async def test_copy_class_carries_schedule_coach_capacity_price_and_pack() -> None:
    sessions = FakeSessions()
    result = await _use_case(sessions, FakeEnrollments(), FakeStudents(rows={})).execute(
        CopySessionCommand(
            source_session_id="src",
            title="Thursday Beginners",
            days_of_week=["Thu"],
            include_price=True,
        )
    )

    copy = result.session
    assert copy.session_id != "src" and sessions.rows[copy.session_id] == copy
    assert copy.title == "Thursday Beginners"
    assert copy.days_of_week == ["Thu"]
    assert (copy.start_time, copy.end_time, copy.timezone) == ("18:00", "19:00", "America/Chicago")
    assert (copy.coach_id, copy.location, copy.capacity) == ("coach-1", "Court 1", 2)
    assert copy.amount_cents == 12000
    assert copy.assistant_coach_ids == ("coach-2",)
    assert copy.what_to_bring == "Racket and water"
    assert result.roster == []


@pytest.mark.asyncio
async def test_copy_without_price_leaves_the_new_class_unpriced() -> None:
    result = await _use_case(FakeSessions(), FakeEnrollments(), FakeStudents(rows={})).execute(
        CopySessionCommand(source_session_id="src", title="Copy", include_price=False)
    )
    assert result.session.amount_cents is None


@pytest.mark.asyncio
async def test_copy_refuses_an_identical_series_like_create_does() -> None:
    with pytest.raises(DuplicateSessionSeries):
        await _use_case(FakeSessions(), FakeEnrollments(), FakeStudents(rows={})).execute(
            CopySessionCommand(source_session_id="src", title="Tuesday Beginners")
        )


@pytest.mark.asyncio
async def test_copy_of_a_missing_class_is_not_found() -> None:
    with pytest.raises(SessionNotFound):
        await _use_case(FakeSessions(), FakeEnrollments(), FakeStudents(rows={})).execute(
            CopySessionCommand(source_session_id="nope", title="Copy")
        )


@pytest.mark.asyncio
async def test_roster_copy_adds_active_students_through_the_seat_check() -> None:
    sessions = FakeSessions()
    enrollments = FakeEnrollments(
        rows=[_enrolled("s1"), _enrolled("s2"), _enrolled("s3"), _enrolled("gone", "dropped")]
    )
    students = FakeStudents(
        rows={
            "s1": _student("s1", "Ana Fake"),
            "s2": _student("s2", "Ben Fake"),
            "s3": _student("s3", "Cy Fake"),
            "gone": _student("gone", "Gus Fake"),
        }
    )

    result = await _use_case(sessions, enrollments, students).execute(
        CopySessionCommand(
            source_session_id="src",
            title="Copy",
            days_of_week=["Thu"],
            copy_roster=True,
            actor_id="admin",
        )
    )

    new_id = result.session.session_id
    # Capacity 2 copied over: the third active student is refused by the
    # same seat check a manual add hits; the dropped one is never copied.
    assert [(r.full_name, r.ok) for r in result.roster] == [
        ("Ana Fake", True),
        ("Ben Fake", True),
        ("Cy Fake", False),
    ]
    assert result.roster[2].error_code == "Enrollment.CapacityExceeded"
    copied = [e for e in enrollments.rows if e.session_id == new_id]
    assert sorted(e.student_id for e in copied) == ["s1", "s2"]
    assert all(e.enrollment_id.startswith("e-") is False for e in copied)
    assert sessions.reserved[new_id] == 2
    # The source roster is untouched.
    assert len([e for e in enrollments.rows if e.session_id == "src"]) == 4


@pytest.mark.asyncio
async def test_copy_defaults_to_no_price() -> None:
    result = await _use_case(FakeSessions(), FakeEnrollments(), FakeStudents(rows={})).execute(
        CopySessionCommand(source_session_id="src", title="Copy", days_of_week=["Thu"])
    )
    assert result.session.amount_cents is None


@pytest.mark.asyncio
async def test_roster_copy_on_the_source_schedule_is_refused_whatever_the_title() -> None:
    sessions = FakeSessions()
    enrollments = FakeEnrollments(rows=[_enrolled("s1")])
    with pytest.raises(CopyRosterRefused):
        await _use_case(sessions, enrollments, FakeStudents(rows={})).execute(
            CopySessionCommand(
                source_session_id="src",
                title="A different title",
                days_of_week=["Tue"],
                start_time="18:00",
                copy_roster=True,
            )
        )
    assert list(sessions.rows) == ["src"]  # refused before any class is created


@pytest.mark.asyncio
async def test_roster_copy_of_a_one_off_class_is_refused() -> None:
    one_off = SOURCE.model_copy(update={"days_of_week": [], "start_time": None, "end_time": None})
    sessions = FakeSessions(rows={"src": one_off})
    with pytest.raises(CopyRosterRefused):
        await _use_case(sessions, FakeEnrollments(), FakeStudents(rows={})).execute(
            CopySessionCommand(source_session_id="src", title="Copy", copy_roster=True)
        )
    assert list(sessions.rows) == ["src"]


@pytest.mark.asyncio
async def test_copy_keeps_every_source_day_when_days_are_not_sent() -> None:
    multi = SOURCE.model_copy(update={"days_of_week": ["Mon", "Wed"]})
    result = await _use_case(
        FakeSessions(rows={"src": multi}), FakeEnrollments(), FakeStudents(rows={})
    ).execute(CopySessionCommand(source_session_id="src", title="Copy", start_time="17:00"))
    assert result.session.days_of_week == ["Mon", "Wed"]
