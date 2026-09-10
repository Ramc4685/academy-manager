"""Use-case tests for parent absence notices (R1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    AbsenceWindowClosed,
    DuplicateAbsenceNotice,
    ListParentAbsences,
    RecordAbsenceNoticeForStudent,
    RecordAbsenceNoticeForStudentCommand,
    SubmitAbsenceNotice,
    SubmitAbsenceNoticeCommand,
)
from backend.v2.contexts.enrollment.domain.errors import OccurrenceNotFound, StudentNotFound
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


# --- RecordAbsenceNoticeForStudent (admin on a parent's behalf, #616) ---------


class _FakeStudentLookup:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._students = students or [_student()]

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [s for s in self._students if s.student_id in student_ids]


def _admin_use_case(
    *,
    occurrences: _FakeOccurrences | None = None,
    students: _FakeStudentLookup | None = None,
    enrollments: _FakeEnrollments | None = None,
    notices: _FakeNotices | None = None,
    notifier: object | None = None,
) -> RecordAbsenceNoticeForStudent:
    return RecordAbsenceNoticeForStudent(
        students=students or _FakeStudentLookup(),
        occurrences=occurrences
        or _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 7, 0, tzinfo=UTC))]),
        enrollments=enrollments or _FakeEnrollments(),
        notices=notices or _FakeNotices(),
        clock=_now,
        notifier=notifier,  # type: ignore[arg-type]
    )


def _admin_cmd(**overrides) -> RecordAbsenceNoticeForStudentCommand:
    return RecordAbsenceNoticeForStudentCommand(
        **{
            "actor_id": "admin-1",
            "student_id": "student-1",
            "occurrence_id": "occ-1",
            **overrides,
        }
    )


@pytest.mark.asyncio
async def test_admin_records_absence_for_past_occurrence() -> None:
    # Occurrence started 07:00, now is 08:00 — a parent would be refused
    # (AbsenceWindowClosed) but the admin path exists precisely for this.
    notices = _FakeNotices()
    use_case = _admin_use_case(notices=notices)

    result = await use_case.execute(_admin_cmd())

    assert result.recorded_by_admin is True
    assert result.submitted_by == "admin-1"
    assert result.notice_window_met is True
    assert result.session_id == "session-1"
    assert result.academy_id == "acad"
    assert result.submitted_at == _now()
    assert notices.added == [result]


@pytest.mark.asyncio
async def test_admin_records_absence_not_counting_toward_makeup() -> None:
    use_case = _admin_use_case()

    result = await use_case.execute(_admin_cmd(counts_toward_makeup=False))

    assert result.notice_window_met is False
    assert result.recorded_by_admin is True


@pytest.mark.asyncio
async def test_admin_record_rejects_unknown_student() -> None:
    use_case = _admin_use_case(students=_FakeStudentLookup([_student("student-9")]))

    with pytest.raises(StudentNotFound):
        await use_case.execute(_admin_cmd())


@pytest.mark.asyncio
async def test_admin_record_rejects_unknown_occurrence() -> None:
    use_case = _admin_use_case()

    with pytest.raises(OccurrenceNotFound):
        await use_case.execute(_admin_cmd(occurrence_id="occ-missing"))


@pytest.mark.asyncio
async def test_admin_record_rejects_student_not_enrolled_in_session() -> None:
    use_case = _admin_use_case(
        enrollments=_FakeEnrollments({("session-1", "student-1"): "dropped"})
    )

    with pytest.raises(StudentNotEnrolledInSession):
        await use_case.execute(_admin_cmd())


@pytest.mark.asyncio
async def test_admin_record_rejects_duplicate_notice() -> None:
    use_case = _admin_use_case()
    await use_case.execute(_admin_cmd())

    with pytest.raises(DuplicateAbsenceNotice):
        await use_case.execute(_admin_cmd())


@pytest.mark.asyncio
async def test_parent_submission_leaves_recorded_by_admin_false() -> None:
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

    assert result.recorded_by_admin is False


# ---------------------------------------------------------------------------
# #616: the notifier port — called once after the write, never able to fail it
# ---------------------------------------------------------------------------


class _RecordingNotifier:
    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self._raise = raise_on_call

    async def absence_notice_submitted(self, *, notice, occurrence, student) -> None:
        self.calls.append({"notice": notice, "occurrence": occurrence, "student": student})
        if self._raise:
            raise RuntimeError("resend is down")


@pytest.mark.asyncio
async def test_parent_submit_calls_notifier_once_with_notice_occurrence_and_student() -> None:
    notifier = _RecordingNotifier()
    notices = _FakeNotices()
    occurrence = _occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences([occurrence]),
        enrollments=_FakeEnrollments(),
        notices=notices,
        policies=_FakePolicies(),
        clock=_now,
        notifier=notifier,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["notice"] is result
    assert call["occurrence"] == occurrence
    assert call["student"].student_id == "student-1"  # type: ignore[attr-defined]
    # The notifier runs after the write, never instead of it.
    assert notices.added == [result]


@pytest.mark.asyncio
async def test_parent_submit_swallows_notifier_failure_and_keeps_the_notice() -> None:
    notifier = _RecordingNotifier(raise_on_call=True)
    notices = _FakeNotices()
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(
            [_occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))]
        ),
        enrollments=_FakeEnrollments(),
        notices=notices,
        policies=_FakePolicies(),
        clock=_now,
        notifier=notifier,
    )

    result = await use_case.execute(
        SubmitAbsenceNoticeCommand(
            parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
        )
    )

    assert len(notifier.calls) == 1
    assert notices.added == [result]


@pytest.mark.asyncio
async def test_parent_submit_without_notifier_is_unchanged() -> None:
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(
            [_occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))]
        ),
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
    assert result.occurrence_id == "occ-1"


@pytest.mark.asyncio
async def test_notifier_is_not_called_when_the_notice_is_rejected() -> None:
    notifier = _RecordingNotifier()
    use_case = SubmitAbsenceNotice(
        students=_FakeStudents(),
        occurrences=_FakeOccurrences(
            [_occurrence(start_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))]
        ),
        enrollments=_FakeEnrollments({}),
        notices=_FakeNotices(),
        policies=_FakePolicies(),
        clock=_now,
        notifier=notifier,
    )
    with pytest.raises(StudentNotEnrolledInSession):
        await use_case.execute(
            SubmitAbsenceNoticeCommand(
                parent_id="parent-1", student_id="student-1", occurrence_id="occ-1"
            )
        )
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_admin_record_calls_notifier_once_with_admin_flagged_notice() -> None:
    notifier = _RecordingNotifier()
    use_case = _admin_use_case(notifier=notifier)

    result = await use_case.execute(_admin_cmd())

    assert len(notifier.calls) == 1
    assert notifier.calls[0]["notice"] is result
    assert result.recorded_by_admin is True
    assert notifier.calls[0]["student"].student_id == "student-1"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_admin_record_swallows_notifier_failure() -> None:
    notifier = _RecordingNotifier(raise_on_call=True)
    notices = _FakeNotices()
    use_case = _admin_use_case(notices=notices, notifier=notifier)

    result = await use_case.execute(_admin_cmd())

    assert len(notifier.calls) == 1
    assert notices.added == [result]
