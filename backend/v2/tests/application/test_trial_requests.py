"""Use-case tests for trial class requests with conversion tracking (R3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    ApproveTrialRequest,
    ApproveTrialRequestCommand,
    DenyTrialRequest,
    DenyTrialRequestCommand,
    LinkTrialConversion,
    ListParentTrialRequests,
    ListTrialRequestsForAdmin,
    SubmitTrialRequest,
    SubmitTrialRequestCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    DuplicateTrialRequest,
    OccurrenceFull,
    OccurrenceRosterEntry,
    TrialRequest,
    TrialRequestNotFound,
    TrialRequestNotPending,
    TrialSessionNotAvailable,
)


def _session(
    *,
    session_id: str = "session-1",
    capacity: int = 2,
    status: str = "scheduled",
) -> Session:
    return Session(
        session_id=session_id,
        academy_id="acad",
        coach_id="coach-1",
        title="Beginner Tennis",
        location="Court 1",
        start_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        end_at=datetime(2026, 7, 1, 11, 0, tzinfo=UTC),
        capacity=capacity,
        status=status,  # type: ignore[arg-type]
    )


def _occurrence(
    *,
    occurrence_id: str = "occ-1",
    session_id: str = "session-1",
    start_at: datetime,
    status: str = "scheduled",
) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id="acad",
        session_id=session_id,
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


class _FakeSessions:
    def __init__(self, sessions: list[Session] | None = None) -> None:
        self._sessions = sessions or [_session()]

    async def get(self, session_id: str) -> Session | None:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        return None

    async def get_many(self, session_ids: list[str]) -> list[Session]:
        return [s for s in self._sessions if s.session_id in session_ids]


class _FakeOccurrences:
    def __init__(self, occurrences: list[SessionOccurrence] | None = None) -> None:
        self._occurrences = occurrences or [
            _occurrence(start_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC))
        ]

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        for o in self._occurrences:
            if o.occurrence_id == occurrence_id:
                return o
        return None


class _FakeEnrollments:
    def __init__(self, active: list[Enrollment] | None = None) -> None:
        self._active = active or []

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._active if e.session_id == session_id]


class _FakeTrials:
    def __init__(self) -> None:
        self.added: list[TrialRequest] = []

    async def add(self, request: TrialRequest) -> None:
        self.added.append(request)

    async def get(self, request_id: str) -> TrialRequest | None:
        for r in self.added:
            if r.request_id == request_id:
                return r
        return None

    async def update(self, request: TrialRequest) -> None:
        for i, r in enumerate(self.added):
            if r.request_id == request.request_id:
                self.added[i] = request
                return

    async def list_for_parent(self, parent_user_id: str) -> list[TrialRequest]:
        rows = [r for r in self.added if r.parent_user_id == parent_user_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    async def list_by_status(self, status: str | None) -> list[TrialRequest]:
        rows = self.added if status is None else [r for r in self.added if r.status == status]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    async def find_pending_for_parent_and_session(
        self, parent_user_id: str, session_id: str
    ) -> TrialRequest | None:
        for r in self.added:
            if (
                r.parent_user_id == parent_user_id
                and r.requested_session_id == session_id
                and r.status == "pending"
            ):
                return r
        return None

    async def find_latest_convertible_for_parent(self, parent_user_id: str) -> TrialRequest | None:
        candidates = [
            r
            for r in self.added
            if r.parent_user_id == parent_user_id
            and r.status in ("approved", "completed")
            and r.linked_application_id is None
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda r: r.created_at, reverse=True)[0]

    async def transition_from_pending(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None:
        for i, r in enumerate(self.added):
            if r.request_id == request_id and r.status == "pending":
                updated = r.model_copy(update=updates)
                self.added[i] = updated
                return updated
        return None


class _FakeOccurrenceRoster:
    def __init__(self) -> None:
        self.added: list[OccurrenceRosterEntry] = []

    async def add(self, entry: OccurrenceRosterEntry) -> None:
        self.added.append(entry)

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        return [e for e in self.added if e.occurrence_id == occurrence_id]

    async def exists(self, occurrence_id: str, student_id: str) -> bool:
        return any(
            e.occurrence_id == occurrence_id and e.student_id == student_id for e in self.added
        )


def _now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


# --- SubmitTrialRequest -------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_trial_request_existing_student_happy_path() -> None:
    trials = _FakeTrials()
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions(),
        trials=trials,
        clock=_now,
    )

    result = await use_case.execute(
        SubmitTrialRequestCommand(
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
        )
    )

    assert result.status == "pending"
    assert result.academy_id == "acad"
    assert result.parent_user_id == "parent-1"
    assert result.student_ref == "existing_student"
    assert result.student_id == "student-1"
    assert result.requested_session_id == "session-1"
    assert trials.added == [result]


@pytest.mark.asyncio
async def test_submit_trial_request_rejects_other_parents_student() -> None:
    use_case = SubmitTrialRequest(
        students=_FakeStudents([_student(parent_id="parent-2")]),
        sessions=_FakeSessions(),
        trials=_FakeTrials(),
        clock=_now,
    )

    with pytest.raises(StudentNotFound):
        await use_case.execute(
            SubmitTrialRequestCommand(
                parent_user_id="parent-1",
                student_ref="existing_student",
                student_id="student-1",
                requested_session_id="session-1",
                preferred_start="2026-07-15",
                preferred_end="2026-07-22",
            )
        )


@pytest.mark.asyncio
async def test_submit_trial_request_prospective_requires_child_name() -> None:
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions(),
        trials=_FakeTrials(),
        clock=_now,
    )

    with pytest.raises(ValueError):
        await use_case.execute(
            SubmitTrialRequestCommand(
                parent_user_id="parent-1",
                student_ref="prospective",
                prospective_child_name=None,
                requested_session_id="session-1",
                preferred_start="2026-07-15",
                preferred_end="2026-07-22",
            )
        )


@pytest.mark.asyncio
async def test_submit_trial_request_prospective_happy_path() -> None:
    trials = _FakeTrials()
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions(),
        trials=trials,
        clock=_now,
    )

    result = await use_case.execute(
        SubmitTrialRequestCommand(
            parent_user_id="parent-1",
            student_ref="prospective",
            prospective_child_name="New Kid",
            prospective_child_dob="2018-01-01",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
        )
    )

    assert result.student_ref == "prospective"
    assert result.student_id is None
    assert result.prospective_child_name == "New Kid"
    assert result.prospective_child_dob == "2018-01-01"


@pytest.mark.asyncio
async def test_submit_trial_request_session_must_exist_and_be_scheduled() -> None:
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions([]),
        trials=_FakeTrials(),
        clock=_now,
    )

    with pytest.raises(TrialSessionNotAvailable):
        await use_case.execute(
            SubmitTrialRequestCommand(
                parent_user_id="parent-1",
                student_ref="existing_student",
                student_id="student-1",
                requested_session_id="session-missing",
                preferred_start="2026-07-15",
                preferred_end="2026-07-22",
            )
        )


@pytest.mark.asyncio
async def test_submit_trial_request_session_not_scheduled_rejected() -> None:
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions([_session(status="cancelled")]),
        trials=_FakeTrials(),
        clock=_now,
    )

    with pytest.raises(TrialSessionNotAvailable):
        await use_case.execute(
            SubmitTrialRequestCommand(
                parent_user_id="parent-1",
                student_ref="existing_student",
                student_id="student-1",
                requested_session_id="session-1",
                preferred_start="2026-07-15",
                preferred_end="2026-07-22",
            )
        )


@pytest.mark.asyncio
async def test_submit_trial_request_duplicate_pending_per_parent_session_conflicts() -> None:
    trials = _FakeTrials()
    use_case = SubmitTrialRequest(
        students=_FakeStudents(),
        sessions=_FakeSessions(),
        trials=trials,
        clock=_now,
    )
    cmd = SubmitTrialRequestCommand(
        parent_user_id="parent-1",
        student_ref="existing_student",
        student_id="student-1",
        requested_session_id="session-1",
        preferred_start="2026-07-15",
        preferred_end="2026-07-22",
    )
    await use_case.execute(cmd)

    with pytest.raises(DuplicateTrialRequest):
        await use_case.execute(cmd)


# --- ListParentTrialRequests / ListTrialRequestsForAdmin ----------------------


@pytest.mark.asyncio
async def test_list_parent_trial_requests_newest_first() -> None:
    trials = _FakeTrials()
    trials.added = [
        TrialRequest(
            request_id="req-1",
            academy_id="acad",
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        TrialRequest(
            request_id="req-2",
            academy_id="acad",
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
            created_at=datetime(2026, 7, 5, tzinfo=UTC),
        ),
    ]
    use_case = ListParentTrialRequests(trials=trials)

    result = await use_case.execute("parent-1")

    assert [r.request_id for r in result] == ["req-2", "req-1"]


@pytest.mark.asyncio
async def test_list_trial_requests_for_admin_filters_by_status() -> None:
    trials = _FakeTrials()
    trials.added = [
        TrialRequest(
            request_id="req-1",
            academy_id="acad",
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
            status="approved",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        TrialRequest(
            request_id="req-2",
            academy_id="acad",
            parent_user_id="parent-1",
            student_ref="existing_student",
            student_id="student-1",
            requested_session_id="session-1",
            preferred_start="2026-07-15",
            preferred_end="2026-07-22",
            status="pending",
            created_at=datetime(2026, 7, 5, tzinfo=UTC),
        ),
    ]
    use_case = ListTrialRequestsForAdmin(trials=trials)

    result = await use_case.execute("pending")

    assert [r.request_id for r in result] == ["req-2"]


# --- ApproveTrialRequest -------------------------------------------------------


def _pending_trial(
    *,
    request_id: str = "req-1",
    student_ref: str = "existing_student",
    student_id: str | None = "student-1",
    session_id: str = "session-1",
) -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id="acad",
        parent_user_id="parent-1",
        student_ref=student_ref,  # type: ignore[arg-type]
        student_id=student_id,
        prospective_child_name=None if student_ref == "existing_student" else "New Kid",
        requested_session_id=session_id,
        preferred_start="2026-07-15",
        preferred_end="2026-07-22",
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_approve_trial_request_existing_student_creates_roster_entry() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial()]
    roster = _FakeOccurrenceRoster()
    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments(),
        sessions=_FakeSessions(),
        occurrence_roster=roster,
        clock=_now,
    )

    result = await use_case.execute(
        ApproveTrialRequestCommand(request_id="req-1", actor_id="admin-1", occurrence_id="occ-1")
    )

    assert result.status == "approved"
    assert result.assigned_occurrence_id == "occ-1"
    assert result.decided_by == "admin-1"
    [entry] = roster.added
    assert entry.occurrence_id == "occ-1"
    assert entry.student_id == "student-1"
    assert entry.source == "trial"
    assert entry.origin_request_id == "req-1"


@pytest.mark.asyncio
async def test_approve_trial_request_prospective_records_occurrence_no_roster_entry() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial(student_ref="prospective", student_id=None)]
    roster = _FakeOccurrenceRoster()
    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments(),
        sessions=_FakeSessions(),
        occurrence_roster=roster,
        clock=_now,
    )

    result = await use_case.execute(
        ApproveTrialRequestCommand(request_id="req-1", actor_id="admin-1", occurrence_id="occ-1")
    )

    assert result.status == "approved"
    assert result.assigned_occurrence_id == "occ-1"
    assert roster.added == []


@pytest.mark.asyncio
async def test_approve_trial_request_capacity_full_raises() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial()]
    active = [
        Enrollment(enrollment_id="e1", academy_id="acad", session_id="session-1", student_id="s1"),
        Enrollment(enrollment_id="e2", academy_id="acad", session_id="session-1", student_id="s2"),
    ]
    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments(active),
        sessions=_FakeSessions([_session(capacity=2)]),
        occurrence_roster=_FakeOccurrenceRoster(),
        clock=_now,
    )

    with pytest.raises(OccurrenceFull):
        await use_case.execute(
            ApproveTrialRequestCommand(
                request_id="req-1", actor_id="admin-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_approve_trial_request_not_found_raises() -> None:
    use_case = ApproveTrialRequest(
        trials=_FakeTrials(),
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments(),
        sessions=_FakeSessions(),
        occurrence_roster=_FakeOccurrenceRoster(),
        clock=_now,
    )

    with pytest.raises(TrialRequestNotFound):
        await use_case.execute(
            ApproveTrialRequestCommand(
                request_id="missing", actor_id="admin-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_approve_trial_request_not_pending_raises() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial().model_copy(update={"status": "denied"})]
    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=_FakeOccurrences(),
        enrollments=_FakeEnrollments(),
        sessions=_FakeSessions(),
        occurrence_roster=_FakeOccurrenceRoster(),
        clock=_now,
    )

    with pytest.raises(TrialRequestNotPending):
        await use_case.execute(
            ApproveTrialRequestCommand(
                request_id="req-1", actor_id="admin-1", occurrence_id="occ-1"
            )
        )


@pytest.mark.asyncio
async def test_approve_trial_request_occurrence_not_future_scheduled_raises() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial()]
    past_occurrence = _occurrence(
        occurrence_id="occ-past", start_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    use_case = ApproveTrialRequest(
        trials=trials,
        occurrences=_FakeOccurrences([past_occurrence]),
        enrollments=_FakeEnrollments(),
        sessions=_FakeSessions(),
        occurrence_roster=_FakeOccurrenceRoster(),
        clock=_now,
    )

    with pytest.raises(TrialSessionNotAvailable):
        await use_case.execute(
            ApproveTrialRequestCommand(
                request_id="req-1", actor_id="admin-1", occurrence_id="occ-past"
            )
        )


# --- DenyTrialRequest -----------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_trial_request_sets_reason() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial()]
    use_case = DenyTrialRequest(trials=trials, clock=_now)

    result = await use_case.execute(
        DenyTrialRequestCommand(request_id="req-1", actor_id="admin-1", reason="no capacity")
    )

    assert result.status == "denied"
    assert result.denial_reason == "no capacity"
    assert result.decided_by == "admin-1"


@pytest.mark.asyncio
async def test_deny_trial_request_not_pending_raises() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial().model_copy(update={"status": "approved"})]
    use_case = DenyTrialRequest(trials=trials, clock=_now)

    with pytest.raises(TrialRequestNotPending):
        await use_case.execute(
            DenyTrialRequestCommand(request_id="req-1", actor_id="admin-1", reason="too late")
        )


# --- LinkTrialConversion ---------------------------------------------------------


@pytest.mark.asyncio
async def test_link_trial_conversion_sets_converted_status() -> None:
    trials = _FakeTrials()
    trials.added = [_pending_trial().model_copy(update={"status": "approved"})]
    use_case = LinkTrialConversion(trials=trials, clock=_now)

    await use_case.execute(parent_user_id="parent-1", application_id="app-1")

    [updated] = trials.added
    assert updated.status == "converted"
    assert updated.linked_application_id == "app-1"


@pytest.mark.asyncio
async def test_link_trial_conversion_no_convertible_trial_is_noop() -> None:
    trials = _FakeTrials()
    use_case = LinkTrialConversion(trials=trials, clock=_now)

    # Should not raise.
    await use_case.execute(parent_user_id="parent-1", application_id="app-1")

    assert trials.added == []


@pytest.mark.asyncio
async def test_link_trial_conversion_picks_newest_convertible() -> None:
    trials = _FakeTrials()
    trials.added = [
        _pending_trial(request_id="req-old").model_copy(
            update={"status": "approved", "created_at": datetime(2026, 6, 1, tzinfo=UTC)}
        ),
        _pending_trial(request_id="req-new").model_copy(
            update={"status": "completed", "created_at": datetime(2026, 7, 1, tzinfo=UTC)}
        ),
    ]
    use_case = LinkTrialConversion(trials=trials, clock=_now)

    await use_case.execute(parent_user_id="parent-1", application_id="app-1")

    converted = [r for r in trials.added if r.status == "converted"]
    assert [r.request_id for r in converted] == ["req-new"]
