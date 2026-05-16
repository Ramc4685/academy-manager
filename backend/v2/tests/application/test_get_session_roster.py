"""GetSessionRoster use-case tests with port fakes."""

from __future__ import annotations

import pytest

from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student


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


@pytest.mark.asyncio
async def test_roster_combines_enrollments_and_students() -> None:
    uc = GetSessionRoster(
        enrollments=FakeEnrollments(
            [_enroll("e1", "st1"), _enroll("e2", "st2"), _enroll("e3", "st3", "cancelled")]
        ),
        students=FakeStudents([_student("st1", "Alice"), _student("st2", "Bob")]),
    )
    roster = await uc.execute("sess")
    assert [r.full_name for r in roster] == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_orphan_enrollment_skipped() -> None:
    uc = GetSessionRoster(
        enrollments=FakeEnrollments([_enroll("e1", "ghost")]),
        students=FakeStudents([]),
    )
    roster = await uc.execute("sess")
    assert roster == []


@pytest.mark.asyncio
async def test_empty_session_short_circuits() -> None:
    uc = GetSessionRoster(
        enrollments=FakeEnrollments([]),
        students=FakeStudents([_student("st1", "Alice")]),
    )
    assert await uc.execute("sess") == []
