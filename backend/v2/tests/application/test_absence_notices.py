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
from backend.v2.contexts.enrollment.domain.self_service import (
    ParentSelfServicePolicy,
    StudentNotEnrolledInSession,
)


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


class _FakeEnrollments:
    """Maps (session_id, student_id) -> enrollment status.

    Defaults to student-1 actively enrolled in session-1 so existing
    happy-path tests keep passing."""

    def __init__(self, enrolled: dict[tuple[str, str], str] | None = None) -> None:
        self._enrolled = (
            enrolled if enrolled is not None else {("session-1", "student-1"): "active"}
        )

    async def is_active_or_paused(self, session_id: str, student_id: str) -> bool:
        return self._enrolled.get((session_id, student_id)) in {"active", "paused"}


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
        enrollments=_FakeEnrollments(),
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
        enrollments=_FakeEnrollments(),
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
        enrollments=_FakeEnrollments(),
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
        enrollments=_FakeEnrollments(),
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
        enrollments=_FakeEnrollments(),
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
        enrollments=_FakeEnrollments(),
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
async def test_submit_absence_notice_rejects_student_not_enrolled_in_session() -> None:
    # Student exists and belongs to the parent, but has NO enrollment in the
    # occurrence's session -> 409 StudentNotEnrolledInSession.
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments({}),
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(StudentNotEnrolledInSession):
        await use_case.execute(
            SubmitAbsenceNoticeCommand(
                parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_submit_absence_notice_allows_paused_enrollment() -> None:
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments({("session-1", "student-1"): "paused"}),
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert result.session_id == "session-1"


@pytest.mark.asyncio
async def test_submit_absence_notice_rejects_cancelled_enrollment() -> None:
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments({("session-1", "student-1"): "cancelled"}),
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(StudentNotEnrolledInSession):
        await use_case.execute(
            SubmitAbsenceNoticeCommand(
                parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
            )
        )


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
        enrollments=_FakeEnrollments(),
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


# --- Repo-level behavior: duplicate-insert race translation ---


@pytest.mark.asyncio
async def test_repo_add_translates_duplicate_key_error_to_domain_409() -> None:
    """A concurrent double-submit can pass the use case's check-then-insert
    pre-check; the unique (academy_id, occurrence_id, student_id) index from
    migration 0145 wins that race at the DB layer, and the repo must
    translate DuplicateKeyError into the same DuplicateAbsenceNotice 409 the
    pre-check raises (not an unhandled 500)."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from pymongo.errors import DuplicateKeyError

    from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
    from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
        MongoAbsenceNoticeRepository,
    )
    from backend.v2.shared.tenancy import tenant_scope

    client = mongomock_motor.AsyncMongoMockClient()
    repo = MongoAbsenceNoticeRepository(client["test"])

    async def _raise_duplicate(_doc: dict[str, object]) -> None:
        raise DuplicateKeyError("E11000 duplicate key error")

    # Deterministic: simulate the index rejecting the losing insert, since
    # mongomock's unique-index enforcement is version-dependent.
    repo._insert_one = _raise_duplicate  # type: ignore[method-assign]

    notice = AbsenceNotice(
        notice_id="notice-1",
        academy_id="acad",
        student_id="student-1",
        occurrence_id="occ-1",
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        notice_window_met=True,
    )

    with tenant_scope("acad"):
        with pytest.raises(DuplicateAbsenceNotice):
            await repo.add(notice)
