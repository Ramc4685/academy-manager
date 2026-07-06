"""Use-case tests for parent absence notices (R1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    AbsenceWindowClosed,
    DuplicateAbsenceNotice,
    ListParentAbsences,
    SubmitAbsenceNotice,
    SubmitAbsenceNoticeCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


def _occurrence(
    *,
    occurrence_id: str = "occ-1",
    start_at: datetime,
    status: str = "scheduled",
) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id="acad",
        session_id="session-1",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
    )


def _student(student_id: str = "student-1", parent_id: str = "parent-1") -> Student:
    return Student(
        student_id=student_id,
        academy_id="acad",
        parent_id=parent_id,
        full_name="Test Student",
    )


class _FakeStudents:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._students = students or [_student()]

    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None:
        for s in self._students:
            if s.student_id == student_id and s.parent_id == parent_id:
                return s
        return None


class _FakeOccurrences:
    def __init__(self, occurrences: list[SessionOccurrence] | None = None) -> None:
        self._occurrences = occurrences or [
            _occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        ]

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        for o in self._occurrences:
            if o.occurrence_id == occurrence_id:
                return o
        return None


class _FakePolicies:
    def __init__(self, policy: ParentSelfServicePolicy | None = None) -> None:
        self._policy = policy or ParentSelfServicePolicy.default("acad")

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return self._policy


class _FakeNotices:
    def __init__(self) -> None:
        self.added: list[object] = []
        self._existing: object | None = None

    async def add(self, notice) -> None:
        self.added.append(notice)
        self._existing = notice

    async def get_for_occurrence_and_student(self, occurrence_id: str, student_id: str):
        if (
            self._existing is not None
            and self._existing.occurrence_id == occurrence_id  # type: ignore[attr-defined]
            and self._existing.student_id == student_id  # type: ignore[attr-defined]
        ):
            return self._existing
        return None

    async def list_for_parent(self, parent_id: str):
        return [n for n in self.added if n.submitted_by == parent_id]  # type: ignore[attr-defined]

    async def list_for_occurrence(self, occurrence_id: str):
        return [n for n in self.added if n.occurrence_id == occurrence_id]  # type: ignore[attr-defined]

    async def list_for_student(self, student_id: str):
        return [n for n in self.added if n.student_id == student_id]  # type: ignore[attr-defined]


def _now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_submit_absence_notice_sets_window_met_true_when_ahead_of_min_hours() -> None:
    # Occurrence starts 2026-07-10 10:00, now is 08:00 -> 2h ahead, min_hours=2
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))])
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=occurrences,
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert result.notice_window_met is True
    assert result.academy_id == "acad"
    assert result.student_id == "student-1"
    assert result.occurrence_id == "occ-1"
    assert result.session_id == "session-1"
    assert result.submitted_by == "parent-1"


@pytest.mark.asyncio
async def test_submit_absence_notice_below_window_still_accepted_with_window_met_false() -> None:
    # Occurrence starts 2026-07-10 08:30, now is 08:00 -> 30min ahead, min_hours=2
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 8, 30, tzinfo=UTC))])
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=occurrences,
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert result.notice_window_met is False


@pytest.mark.asyncio
async def test_submit_absence_notice_rejects_already_started_occurrence() -> None:
    # Occurrence started 2026-07-10 07:00, now is 08:00 -> already started
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 7, 0, tzinfo=UTC))])
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=occurrences,
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(AbsenceWindowClosed):
        await use_case.execute(
            SubmitAbsenceNoticeCommand(
                parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_submit_absence_notice_rejects_other_parents_student() -> None:
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents([_student(parent_id="parent-2")]),
        occurrences=_FakeOccurrences(),
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(StudentNotFound):
        await use_case.execute(
            SubmitAbsenceNoticeCommand(
                parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_submit_absence_notice_rejects_duplicate() -> None:
    notices = _FakeNotices()
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(),
        notices=notices,
        policies=_FakePolicies(),
        clock=_now,
    )
    cmd = SubmitAbsenceNoticeCommand(
        parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
    )
    await use_case.execute(cmd)

    with pytest.raises(DuplicateAbsenceNotice):
        await use_case.execute(cmd)


@pytest.mark.asyncio
async def test_list_parent_absences_returns_only_parents_notices() -> None:
    notices = _FakeNotices()
    submit = SubmitAbsenceNotice(
        students=_FakeStudents([_student(student_id="student-1", parent_id="parent-1")]),
        occurrences=_FakeOccurrences(),
        notices=notices,
        policies=_FakePolicies(),
        clock=_now,
    )
    await submit.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    list_use_case = ListParentAbsences(notices=notices)
    result = await list_use_case.execute("parent-1")

    assert len(result) == 1
    assert result[0].submitted_by == "parent-1"


@pytest.mark.asyncio
async def test_submit_absence_notice_uses_policy_min_hours() -> None:
    # min_hours = 4; occurrence starts 3h ahead -> window not met
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 11, 0, tzinfo=UTC))])
    policy = ParentSelfServicePolicy.default("acad").model_copy(
        update={"absence_notice_min_hours": 4}
    )
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=occurrences,
        notices=_FakeNotices(),
        policies=_FakePolicies(policy),
        clock=_now,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert result.notice_window_met is False
