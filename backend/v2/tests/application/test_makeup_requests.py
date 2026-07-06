"""Use-case tests for parent makeup requests (R2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ListEligibleMakeupTargets,
    ListParentMakeups,
    SubmitMakeupRequest,
    SubmitMakeupRequestCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    DuplicateMakeupRequest,
    MakeupNotEligible,
    MakeupRequest,
    MakeupWindowExpired,
    OccurrenceRosterEntry,
    ParentSelfServicePolicy,
)


def _occurrence(
    *,
    occurrence_id: str = "occ-missed",
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


class _FakeOccurrences:
    def __init__(self, occurrences: list[SessionOccurrence] | None = None) -> None:
        self._occurrences = occurrences or [
            _occurrence(start_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
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
    def __init__(self, notices: list[AbsenceNotice] | None = None) -> None:
        self._notices = notices or []

    async def get_for_occurrence_and_student(
        self, occurrence_id: str, student_id: str
    ) -> AbsenceNotice | None:
        for n in self._notices:
            if n.occurrence_id == occurrence_id and n.student_id == student_id:
                return n
        return None


class _FakeMakeups:
    def __init__(self) -> None:
        self.added: list[MakeupRequest] = []

    async def add(self, request: MakeupRequest) -> None:
        self.added.append(request)

    async def find_active_for_missed_occurrence(
        self, missed_occurrence_id: str, student_id: str
    ) -> MakeupRequest | None:
        for r in self.added:
            if (
                r.missed_occurrence_id == missed_occurrence_id
                and r.student_id == student_id
                and r.status != "denied"
            ):
                return r
        return None

    async def list_for_parent(self, parent_id: str) -> list[MakeupRequest]:
        return [r for r in self.added if r.parent_id == parent_id]


def _now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def _absence_notice(
    *,
    occurrence_id: str = "occ-missed",
    student_id: str = "student-1",
    window_met: bool = True,
) -> AbsenceNotice:
    return AbsenceNotice(
        notice_id="notice-1",
        academy_id="acad",
        student_id=student_id,
        occurrence_id=occurrence_id,
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
        notice_window_met=window_met,
    )


def _make_use_case(
    *,
    occurrences: _FakeOccurrences | None = None,
    notices: _FakeNotices | None = None,
    makeups: _FakeMakeups | None = None,
    policy: ParentSelfServicePolicy | None = None,
    clock=_now,
) -> tuple[SubmitMakeupRequest, _FakeMakeups]:
    makeups = makeups or _FakeMakeups()
    use_case = SubmitMakeupRequest(
        students=_FakeStudents(),
        occurrences=occurrences or _FakeOccurrences(),
        notices=notices or _FakeNotices([_absence_notice()]),
        makeups=makeups,
        policies=_FakePolicies(policy),
        clock=clock,
    )
    return use_case, makeups


@pytest.mark.asyncio
async def test_submit_makeup_request_happy_path() -> None:
    # Missed occurrence started 2026-07-01 10:00 (past), notice window met,
    # now (2026-07-10) is within the 30-day default expiry.
    use_case, makeups = _make_use_case()

    result = await use_case.execute(
        SubmitMakeupRequestCommand(
            parent_id="parent-1",
            student_id="student-1",
            missed_occurrence_id="occ-missed",
        )
    )

    assert result.status == "pending"
    assert result.academy_id == "acad"
    assert result.student_id == "student-1"
    assert result.parent_id == "parent-1"
    assert result.missed_occurrence_id == "occ-missed"
    assert result.requested_target_occurrence_id is None
    assert result.expires_at == datetime(2026, 7, 1, 10, 0, tzinfo=UTC) + timedelta(days=30)
    assert makeups.added == [result]


@pytest.mark.asyncio
async def test_submit_makeup_request_with_requested_target() -> None:
    use_case, _ = _make_use_case()

    result = await use_case.execute(
        SubmitMakeupRequestCommand(
            parent_id="parent-1",
            student_id="student-1",
            missed_occurrence_id="occ-missed",
            requested_target_occurrence_id="occ-target",
        )
    )

    assert result.requested_target_occurrence_id == "occ-target"


@pytest.mark.asyncio
async def test_submit_makeup_request_rejects_other_parents_student() -> None:
    use_case = SubmitMakeupRequest(
        students=_FakeStudents([_student(parent_id="parent-2")]),
        occurrences=_FakeOccurrences(),
        notices=_FakeNotices([_absence_notice()]),
        makeups=_FakeMakeups(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(StudentNotFound):
        await use_case.execute(
            SubmitMakeupRequestCommand(
                parent_id="parent-1",
                student_id="student-1",
                missed_occurrence_id="occ-missed",
            )
        )


@pytest.mark.asyncio
async def test_submit_makeup_request_rejects_future_occurrence() -> None:
    # now = 2026-07-10 08:00; occurrence starts in the future -> can't request makeup yet
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))])
    use_case, _ = _make_use_case(occurrences=occurrences)

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            SubmitMakeupRequestCommand(
                parent_id="parent-1",
                student_id="student-1",
                missed_occurrence_id="occ-missed",
            )
        )


@pytest.mark.asyncio
async def test_submit_makeup_request_requires_window_met_notice_when_policy_demands_it() -> None:
    # notice exists but window_met is False
    notices = _FakeNotices([_absence_notice(window_met=False)])
    use_case, _ = _make_use_case(notices=notices)

    with pytest.raises(MakeupNotEligible):
        await use_case.execute(
            SubmitMakeupRequestCommand(
                parent_id="parent-1",
                student_id="student-1",
                missed_occurrence_id="occ-missed",
            )
        )


@pytest.mark.asyncio
async def test_submit_makeup_request_no_notice_at_all_not_eligible_when_required() -> None:
    use_case, _ = _make_use_case(notices=_FakeNotices([]))

    with pytest.raises(MakeupNotEligible):
        await use_case.execute(
            SubmitMakeupRequestCommand(
                parent_id="parent-1",
                student_id="student-1",
                missed_occurrence_id="occ-missed",
            )
        )


@pytest.mark.asyncio
async def test_submit_makeup_request_skips_notice_check_when_policy_does_not_require_it() -> None:
    policy = ParentSelfServicePolicy.default("acad").model_copy(
        update={"makeup_requires_notice": False}
    )
    use_case, _ = _make_use_case(notices=_FakeNotices([]), policy=policy)

    result = await use_case.execute(
        SubmitMakeupRequestCommand(
            parent_id="parent-1",
            student_id="student-1",
            missed_occurrence_id="occ-missed",
        )
    )

    assert result.status == "pending"


@pytest.mark.asyncio
async def test_submit_makeup_request_rejects_past_expiry_window() -> None:
    # Occurrence started 2026-05-01; default expiry is 30 days; now (2026-07-10)
    # is well past missed.start_at + 30 days.
    occurrences = _FakeOccurrences([_occurrence(start_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC))])
    notices = _FakeNotices([_absence_notice()])
    use_case, _ = _make_use_case(occurrences=occurrences, notices=notices)

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            SubmitMakeupRequestCommand(
                parent_id="parent-1",
                student_id="student-1",
                missed_occurrence_id="occ-missed",
            )
        )


@pytest.mark.asyncio
async def test_submit_makeup_request_rejects_duplicate_non_denied() -> None:
    makeups = _FakeMakeups()
    use_case, makeups = _make_use_case(makeups=makeups)
    cmd = SubmitMakeupRequestCommand(
        parent_id="parent-1",
        student_id="student-1",
        missed_occurrence_id="occ-missed",
    )
    await use_case.execute(cmd)

    with pytest.raises(DuplicateMakeupRequest):
        await use_case.execute(cmd)


@pytest.mark.asyncio
async def test_submit_makeup_request_denied_request_does_not_block_new_one() -> None:
    makeups = _FakeMakeups()
    makeups.added.append(
        MakeupRequest(
            request_id="req-denied",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-missed",
            status="denied",
            expires_at=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
            created_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        )
    )
    use_case, makeups = _make_use_case(makeups=makeups)

    result = await use_case.execute(
        SubmitMakeupRequestCommand(
            parent_id="parent-1",
            student_id="student-1",
            missed_occurrence_id="occ-missed",
        )
    )

    assert result.status == "pending"
    assert len(makeups.added) == 2


# --- ListParentMakeups -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_parent_makeups_returns_all_statuses() -> None:
    makeups = _FakeMakeups()
    makeups.added.extend(
        [
            MakeupRequest(
                request_id="req-pending",
                academy_id="acad",
                student_id="student-1",
                parent_id="parent-1",
                missed_occurrence_id="occ-1",
                status="pending",
                expires_at=datetime(2026, 7, 31, tzinfo=UTC),
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            ),
            MakeupRequest(
                request_id="req-expired",
                academy_id="acad",
                student_id="student-1",
                parent_id="parent-1",
                missed_occurrence_id="occ-2",
                status="expired",
                expires_at=datetime(2026, 6, 1, tzinfo=UTC),
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        ]
    )
    list_use_case = ListParentMakeups(makeups=makeups)

    result = await list_use_case.execute("parent-1")

    assert {r.request_id for r in result} == {"req-pending", "req-expired"}


# --- ListEligibleMakeupTargets ---------------------------------------------


def _session(
    session_id: str = "session-target",
    capacity: int = 2,
) -> Session:
    return Session(
        session_id=session_id,
        academy_id="acad",
        coach_id="coach-1",
        title="Target session",
        location="Court 1",
        start_at=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
        end_at=datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
        capacity=capacity,
    )


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


class _FakeEnrollments:
    def __init__(self, enrollments: list[Enrollment] | None = None) -> None:
        self._enrollments = enrollments or []

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.session_id == session_id]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id for e in self._enrollments
        )


class _FakeOccurrenceRoster:
    def __init__(self, entries: list[OccurrenceRosterEntry] | None = None) -> None:
        self._entries = entries or []

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        return [e for e in self._entries if e.occurrence_id == occurrence_id]


def _target_occurrence(
    *,
    occurrence_id: str,
    session_id: str,
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


class _FakeOccurrencesForTargets:
    """Serves both the missed occurrence lookup and upcoming candidates."""

    def __init__(
        self,
        *,
        missed: SessionOccurrence,
        candidates: list[SessionOccurrence],
    ) -> None:
        self._missed = missed
        self._candidates = candidates

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        if occurrence_id == self._missed.occurrence_id:
            return self._missed
        for c in self._candidates:
            if c.occurrence_id == occurrence_id:
                return c
        return None

    async def list_upcoming_scheduled_between(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[SessionOccurrence]:
        return [
            c
            for c in self._candidates
            if c.status == "scheduled" and start_at <= c.start_at <= end_at
        ]


def _make_targets_use_case(
    *,
    missed_start_at: datetime = datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    candidates: list[SessionOccurrence] | None = None,
    sessions: list[Session] | None = None,
    enrollments: list[Enrollment] | None = None,
    roster_entries: list[OccurrenceRosterEntry] | None = None,
    policy: ParentSelfServicePolicy | None = None,
    clock=_now,
) -> ListEligibleMakeupTargets:
    missed = _occurrence(occurrence_id="occ-missed", start_at=missed_start_at)
    occurrences = _FakeOccurrencesForTargets(
        missed=missed,
        candidates=candidates
        or [
            _target_occurrence(
                occurrence_id="occ-target",
                session_id="session-target",
                start_at=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
            )
        ],
    )
    return ListEligibleMakeupTargets(
        students=_FakeStudents(),
        occurrences=occurrences,
        sessions=_FakeSessions(sessions or [_session()]),
        enrollments=_FakeEnrollments(enrollments or []),
        occurrence_roster=_FakeOccurrenceRoster(roster_entries or []),
        policies=_FakePolicies(policy),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_returns_open_slots() -> None:
    use_case = _make_targets_use_case()

    result = await use_case.execute(
        parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
    )

    assert len(result) == 1
    target = result[0]
    assert target.occurrence_id == "occ-target"
    assert target.session_id == "session-target"
    assert target.title == "Target session"
    assert target.open_slots == 2  # capacity 2, no enrollments, no roster entries


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_excludes_full_capacity() -> None:
    session = _session(session_id="session-target", capacity=1)
    enrollments = [
        Enrollment(
            enrollment_id="e1",
            academy_id="acad",
            session_id="session-target",
            student_id="other-student",
            status="active",
        )
    ]
    use_case = _make_targets_use_case(sessions=[session], enrollments=enrollments)

    result = await use_case.execute(
        parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_accounts_for_roster_entries_in_capacity() -> None:
    session = _session(session_id="session-target", capacity=1)
    roster_entries = [
        OccurrenceRosterEntry(
            entry_id="entry-1",
            academy_id="acad",
            occurrence_id="occ-target",
            student_id="other-student",
            source="makeup",
            origin_request_id="req-x",
            created_at=datetime(2026, 7, 5, tzinfo=UTC),
        )
    ]
    use_case = _make_targets_use_case(sessions=[session], roster_entries=roster_entries)

    result = await use_case.execute(
        parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_excludes_own_enrolled_session() -> None:
    enrollments = [
        Enrollment(
            enrollment_id="e1",
            academy_id="acad",
            session_id="session-target",
            student_id="student-1",
            status="active",
        )
    ]
    use_case = _make_targets_use_case(enrollments=enrollments)

    result = await use_case.execute(
        parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_respects_expiry_window() -> None:
    # missed occurrence started 2026-07-01; default expiry 30 days -> window
    # ends 2026-07-31. A candidate after that should be excluded.
    out_of_window = _target_occurrence(
        occurrence_id="occ-too-late",
        session_id="session-target",
        start_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
    )
    use_case = _make_targets_use_case(candidates=[out_of_window])

    result = await use_case.execute(
        parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_eligible_makeup_targets_rejects_other_parents_student() -> None:
    use_case = ListEligibleMakeupTargets(
        students=_FakeStudents([_student(parent_id="parent-2")]),
        occurrences=_FakeOccurrencesForTargets(
            missed=_occurrence(
                occurrence_id="occ-missed", start_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
            ),
            candidates=[],
        ),
        sessions=_FakeSessions(),
        enrollments=_FakeEnrollments(),
        occurrence_roster=_FakeOccurrenceRoster(),
        policies=_FakePolicies(),
        clock=_now,
    )

    with pytest.raises(StudentNotFound):
        await use_case.execute(
            parent_id="parent-1", student_id="student-1", missed_occurrence_id="occ-missed"
        )
