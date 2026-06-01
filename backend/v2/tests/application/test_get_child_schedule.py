"""GetChildSchedule use-case unit tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    GetChildSchedule,
    StudentNotOwnedByParent,
)
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)

# --- Fakes ---


class FakeStudentQuery:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None:
        s = self._by_id.get(student_id)
        if s and s.parent_id == parent_id:
            return s
        return None


class FakeEnrollmentQuery:
    def __init__(self, enrollments: list[Enrollment]) -> None:
        self._enrollments = enrollments

    async def active_for_student(self, student_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.student_id == student_id and e.status == "active"]


class FakeOccurrenceQuery:
    def __init__(self, occurrences: list[SessionOccurrence]) -> None:
        self._occurrences = occurrences

    async def list_for_session_between(
        self, *, session_id: str, start_at: datetime, end_at: datetime
    ) -> list[SessionOccurrence]:
        return [
            o
            for o in self._occurrences
            if o.session_id == session_id and start_at <= o.start_at <= end_at
        ]


class FakeSessionQuery:
    def __init__(self, sessions: list[Session]) -> None:
        self._by_id = {s.session_id: s for s in sessions}

    async def get(self, session_id: str) -> Session | None:
        return self._by_id.get(session_id)

    async def get_many(self, session_ids: list[str]) -> list[Session]:
        return [self._by_id[sid] for sid in session_ids if sid in self._by_id]


# --- Helpers ---


def _student(sid: str, parent_id: str = "parent-1") -> Student:
    return Student(student_id=sid, academy_id="acad", parent_id=parent_id, full_name="Alice")


def _session(sid: str, title: str = "Morning Squad", coach_id: str = "coach-1") -> Session:
    return Session(
        session_id=sid,
        academy_id="acad",
        coach_id=coach_id,
        title=title,
        location="Court A",
        start_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        capacity=10,
    )


def _enrollment(eid: str, student_id: str, session_id: str, status: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id=eid,
        academy_id="acad",
        session_id=session_id,
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
    )


def _occurrence(
    oid: str,
    session_id: str,
    start_at: datetime,
    end_at: datetime | None = None,
    scheduled_coach_id: str = "coach-1",
    status: str = "scheduled",
) -> SessionOccurrence:
    if end_at is None:
        end_at = start_at + timedelta(hours=1)
    return SessionOccurrence(
        occurrence_id=oid,
        academy_id="acad",
        session_id=session_id,
        start_at=start_at,
        end_at=end_at,
        scheduled_coach_id=scheduled_coach_id,
        status=status,  # type: ignore[arg-type]
    )


_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_IN_2_DAYS = _NOW + timedelta(days=2)
_IN_10_DAYS = _NOW + timedelta(days=10)
_IN_40_DAYS = _NOW + timedelta(days=40)  # outside default 30-day window
_YESTERDAY = _NOW - timedelta(days=1)


def _make_uc(
    students: list[Student],
    enrollments: list[Enrollment],
    occurrences: list[SessionOccurrence],
    sessions: list[Session],
) -> GetChildSchedule:
    return GetChildSchedule(
        enrollments=FakeEnrollmentQuery(enrollments),
        occurrences=FakeOccurrenceQuery(occurrences),
        sessions=FakeSessionQuery(sessions),
        students=FakeStudentQuery(students),
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_happy_path_returns_upcoming_occurrences_ordered_by_start_at() -> None:
    student = _student("st-1")
    session = _session("sess-1")
    occ_near = _occurrence("occ-1", "sess-1", _IN_2_DAYS)
    occ_far = _occurrence("occ-2", "sess-1", _IN_10_DAYS)

    uc = _make_uc([student], [_enrollment("e1", "st-1", "sess-1")], [occ_near, occ_far], [session])
    entries, total = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    assert len(entries) == 2
    assert total == 2
    assert entries[0].occurrence_id == "occ-1"
    assert entries[1].occurrence_id == "occ-2"
    assert entries[0].session_title == "Morning Squad"
    assert entries[0].session_id == "sess-1"
    assert entries[0].status == "scheduled"


@pytest.mark.asyncio
async def test_default_range_excludes_past_occurrences() -> None:
    student = _student("st-1")
    session = _session("sess-1")
    occ_past = _occurrence("occ-past", "sess-1", _YESTERDAY)
    occ_future = _occurrence("occ-future", "sess-1", _IN_2_DAYS)

    uc = _make_uc(
        [student],
        [_enrollment("e1", "st-1", "sess-1")],
        [occ_past, occ_future],
        [session],
    )
    entries, _ = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    occurrence_ids = [r.occurrence_id for r in entries]
    assert "occ-past" not in occurrence_ids
    assert "occ-future" in occurrence_ids


@pytest.mark.asyncio
async def test_default_range_excludes_occurrences_beyond_30_days() -> None:
    student = _student("st-1")
    session = _session("sess-1")
    occ_in_window = _occurrence("occ-in", "sess-1", _IN_10_DAYS)
    occ_out_of_window = _occurrence("occ-out", "sess-1", _IN_40_DAYS)

    uc = _make_uc(
        [student],
        [_enrollment("e1", "st-1", "sess-1")],
        [occ_in_window, occ_out_of_window],
        [session],
    )
    entries, _ = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    occurrence_ids = [r.occurrence_id for r in entries]
    assert "occ-in" in occurrence_ids
    assert "occ-out" not in occurrence_ids


@pytest.mark.asyncio
async def test_explicit_date_range_filter() -> None:
    student = _student("st-1")
    session = _session("sess-1")
    # Two occurrences, one inside explicit range, one outside
    in_range = _occurrence("occ-a", "sess-1", datetime(2026, 7, 5, 9, 0, tzinfo=UTC))
    out_range = _occurrence("occ-b", "sess-1", datetime(2026, 8, 1, 9, 0, tzinfo=UTC))

    uc = _make_uc(
        [student],
        [_enrollment("e1", "st-1", "sess-1")],
        [in_range, out_range],
        [session],
    )
    entries, _ = await uc.execute(
        "parent-1",
        "st-1",
        frm=date(2026, 7, 1),
        to=date(2026, 7, 31),
        limit=50,
        offset=0,
    )

    occurrence_ids = [r.occurrence_id for r in entries]
    assert "occ-a" in occurrence_ids
    assert "occ-b" not in occurrence_ids


@pytest.mark.asyncio
async def test_non_owned_student_raises_error() -> None:
    student = _student("st-1", parent_id="other-parent")

    uc = _make_uc([student], [], [], [])
    with pytest.raises(StudentNotOwnedByParent):
        await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)


@pytest.mark.asyncio
async def test_unknown_student_raises_error() -> None:
    uc = _make_uc([], [], [], [])
    with pytest.raises(StudentNotOwnedByParent):
        await uc.execute("parent-1", "no-such-student", frm=None, to=None, limit=50, offset=0)


@pytest.mark.asyncio
async def test_pagination_offset_and_limit() -> None:
    student = _student("st-1")
    session = _session("sess-1")
    occs = [_occurrence(f"occ-{i}", "sess-1", _IN_2_DAYS + timedelta(hours=i)) for i in range(5)]

    uc = _make_uc([student], [_enrollment("e1", "st-1", "sess-1")], occs, [session])
    page1_entries, page1_total = await uc.execute(
        "parent-1", "st-1", frm=None, to=None, limit=2, offset=0
    )
    page2_entries, page2_total = await uc.execute(
        "parent-1", "st-1", frm=None, to=None, limit=2, offset=2
    )

    assert len(page1_entries) == 2
    assert page1_total == 5  # full collection size, not page size
    assert len(page2_entries) == 2
    assert page2_total == 5
    assert page1_entries[0].occurrence_id == "occ-0"
    assert page2_entries[0].occurrence_id == "occ-2"


@pytest.mark.asyncio
async def test_coach_name_is_none_when_session_has_no_name_field() -> None:
    """Coach name is sourced from session.coach_id — if not resolved it stays None."""
    student = _student("st-1")
    session = _session("sess-1", coach_id="coach-99")
    occ = _occurrence("occ-1", "sess-1", _IN_2_DAYS, scheduled_coach_id="coach-99")

    uc = _make_uc([student], [_enrollment("e1", "st-1", "sess-1")], [occ], [session])
    entries, _ = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    # coach_name is None because there's no user lookup in the use case
    assert entries[0].coach_name is None


@pytest.mark.asyncio
async def test_cancelled_occurrences_are_included() -> None:
    """Schedule shows all statuses so parent can see cancellations."""
    student = _student("st-1")
    session = _session("sess-1")
    occ = _occurrence("occ-1", "sess-1", _IN_2_DAYS, status="cancelled")

    uc = _make_uc([student], [_enrollment("e1", "st-1", "sess-1")], [occ], [session])
    entries, total = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    assert len(entries) == 1
    assert total == 1
    assert entries[0].status == "cancelled"


@pytest.mark.asyncio
async def test_only_active_enrollments_are_included() -> None:
    student = _student("st-1")
    session_active = _session("sess-active")
    session_cancelled = _session("sess-cancelled")
    occ_active = _occurrence("occ-active", "sess-active", _IN_2_DAYS)
    occ_cancelled = _occurrence("occ-cancelled", "sess-cancelled", _IN_2_DAYS)

    uc = _make_uc(
        [student],
        [
            _enrollment("e1", "st-1", "sess-active", "active"),
            _enrollment("e2", "st-1", "sess-cancelled", "cancelled"),
        ],
        [occ_active, occ_cancelled],
        [session_active, session_cancelled],
    )
    entries, _ = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)

    occurrence_ids = [r.occurrence_id for r in entries]
    assert "occ-active" in occurrence_ids
    assert "occ-cancelled" not in occurrence_ids


@pytest.mark.asyncio
async def test_no_enrollments_returns_empty() -> None:
    student = _student("st-1")
    uc = _make_uc([student], [], [], [])
    entries, total = await uc.execute("parent-1", "st-1", frm=None, to=None, limit=50, offset=0)
    assert entries == []
    assert total == 0
