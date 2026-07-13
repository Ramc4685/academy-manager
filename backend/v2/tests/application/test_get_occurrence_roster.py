"""GetOccurrenceRoster use-case tests with port fakes.

Coach-today reads are per-occurrence (unlike GetSessionRoster, which is
session-scoped and used by several other callers we must not disturb).
This use case wraps GetSessionRoster's output for one occurrence and:
  - flags `expected_absence=True` when an AbsenceNotice exists for
    (occurrence_id, student_id)
  - appends one-time OccurrenceRosterEntry rows (makeup/trial) with
    `entry_source` set accordingly
  - tags regular enrollment-backed rows with `entry_source="enrollment"`
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    GetOccurrenceRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry


class FakeEnrollments:
    def __init__(self, enrollments: list[Enrollment]) -> None:
        self._enrollments = enrollments

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.session_id == session_id and e.status == "active"]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self._enrollments
        )


class FakeStudents:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._by_id[sid] for sid in student_ids if sid in self._by_id]


class FakeAbsenceNotices:
    def __init__(self, notices: list[AbsenceNotice] | None = None) -> None:
        self._notices = notices or []

    async def list_for_occurrence(self, occurrence_id: str) -> list[AbsenceNotice]:
        return [n for n in self._notices if n.occurrence_id == occurrence_id]


class FakeOccurrenceRoster:
    def __init__(self, entries: list[OccurrenceRosterEntry] | None = None) -> None:
        self._entries = entries or []

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        return [e for e in self._entries if e.occurrence_id == occurrence_id]


def _student(sid: str, name: str) -> Student:
    return Student(student_id=sid, academy_id="acad", parent_id="p", full_name=name)


def _enroll(eid: str, sid: str, st: str = "active") -> Enrollment:
    return Enrollment(
        enrollment_id=eid,
        academy_id="acad",
        session_id="sess",
        student_id=sid,
        status=st,  # type: ignore[arg-type]
    )


def _notice(occurrence_id: str, student_id: str) -> AbsenceNotice:
    return AbsenceNotice(
        notice_id="notice-1",
        academy_id="acad",
        student_id=student_id,
        occurrence_id=occurrence_id,
        session_id="sess",
        submitted_by="parent-1",
        submitted_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        notice_window_met=True,
    )


def _one_time_entry(
    *, entry_id: str, occurrence_id: str, student_id: str, source: str
) -> OccurrenceRosterEntry:
    return OccurrenceRosterEntry(
        entry_id=entry_id,
        academy_id="acad",
        occurrence_id=occurrence_id,
        student_id=student_id,
        source=source,  # type: ignore[arg-type]
        origin_request_id="req-1",
        created_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_enrollment_backed_entries_get_entry_source_enrollment_and_no_absence() -> None:
    students = FakeStudents([_student("st1", "Alice")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([_enroll("e1", "st1")]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices(),
        occurrence_roster=FakeOccurrenceRoster(),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert len(result) == 1
    entry = result[0]
    assert entry.student_id == "st1"
    assert entry.entry_source == "enrollment"
    assert entry.expected_absence is False


@pytest.mark.asyncio
async def test_student_with_absence_notice_flagged_expected_absence() -> None:
    students = FakeStudents([_student("st1", "Alice"), _student("st2", "Bob")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([_enroll("e1", "st1"), _enroll("e2", "st2")]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices([_notice("occ-1", "st1")]),
        occurrence_roster=FakeOccurrenceRoster(),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    by_id = {e.student_id: e for e in result}
    assert by_id["st1"].expected_absence is True
    assert by_id["st2"].expected_absence is False


@pytest.mark.asyncio
async def test_absence_notice_for_other_occurrence_does_not_leak() -> None:
    students = FakeStudents([_student("st1", "Alice")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([_enroll("e1", "st1")]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices([_notice("occ-other", "st1")]),
        occurrence_roster=FakeOccurrenceRoster(),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert result[0].expected_absence is False


@pytest.mark.asyncio
async def test_one_time_makeup_entry_appended_with_entry_source_makeup() -> None:
    students = FakeStudents([_student("st1", "Alice"), _student("st-makeup", "Charlie")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([_enroll("e1", "st1")]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices(),
        occurrence_roster=FakeOccurrenceRoster(
            [
                _one_time_entry(
                    entry_id="ore-1",
                    occurrence_id="occ-1",
                    student_id="st-makeup",
                    source="makeup",
                )
            ]
        ),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert len(result) == 2
    by_id = {e.student_id: e for e in result}
    assert by_id["st-makeup"].entry_source == "makeup"
    assert by_id["st-makeup"].full_name == "Charlie"
    assert by_id["st-makeup"].enrollment_id is None
    assert by_id["st1"].entry_source == "enrollment"


@pytest.mark.asyncio
async def test_one_time_trial_entry_appended_with_entry_source_trial() -> None:
    students = FakeStudents([_student("st-trial", "Dana")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices(),
        occurrence_roster=FakeOccurrenceRoster(
            [
                _one_time_entry(
                    entry_id="ore-2",
                    occurrence_id="occ-1",
                    student_id="st-trial",
                    source="trial",
                )
            ]
        ),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert len(result) == 1
    assert result[0].entry_source == "trial"
    assert result[0].full_name == "Dana"


@pytest.mark.asyncio
async def test_one_time_entry_for_other_occurrence_not_included() -> None:
    students = FakeStudents([_student("st-trial", "Dana")])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices(),
        occurrence_roster=FakeOccurrenceRoster(
            [
                _one_time_entry(
                    entry_id="ore-3",
                    occurrence_id="occ-other",
                    student_id="st-trial",
                    source="trial",
                )
            ]
        ),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert result == []


@pytest.mark.asyncio
async def test_one_time_entry_missing_student_skipped_not_crashed() -> None:
    """Orphan one-time entry (student record missing) is skipped, mirroring
    GetSessionRoster's orphan-enrollment handling."""
    students = FakeStudents([])
    uc = GetOccurrenceRoster(
        get_roster=GetSessionRoster(
            enrollments=FakeEnrollments([]),
            students=students,
        ),
        absence_notices=FakeAbsenceNotices(),
        occurrence_roster=FakeOccurrenceRoster(
            [
                _one_time_entry(
                    entry_id="ore-4",
                    occurrence_id="occ-1",
                    student_id="st-ghost",
                    source="makeup",
                )
            ]
        ),
        students=students,
    )
    result = await uc.execute(session_id="sess", occurrence_id="occ-1")

    assert result == []
