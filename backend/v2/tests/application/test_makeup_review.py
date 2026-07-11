"""Use-case tests for admin makeup review (R2, Task 5).

Admin approves/denies parent-submitted makeup requests, and can list both
absence notices and makeup requests for review. Approval writes a one-time
occurrence roster entry via the Task 3 repo and must have NO billing
dependency whatsoever — the student already paid for the missed session.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ApproveMakeupRequest,
    ApproveMakeupRequestCommand,
    DenyMakeupRequest,
    DenyMakeupRequestCommand,
    ListAbsencesForAdmin,
    ListMakeupRequestsForAdmin,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import (
    MakeupRequest,
    MakeupRequestNotFound,
    MakeupRequestNotPending,
    MakeupWindowExpired,
    OccurrenceFull,
    OccurrenceRosterEntry,
)


def _now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def _pending_request(
    *,
    request_id: str = "req-1",
    student_id: str = "student-1",
    parent_id: str = "parent-1",
    missed_occurrence_id: str = "occ-missed",
    expires_at: datetime | None = None,
    status: str = "pending",
) -> MakeupRequest:
    return MakeupRequest(
        request_id=request_id,
        academy_id="acad",
        student_id=student_id,
        parent_id=parent_id,
        missed_occurrence_id=missed_occurrence_id,
        status=status,  # type: ignore[arg-type]
        expires_at=expires_at or _now() + timedelta(days=5),
        created_at=_now() - timedelta(days=1),
    )


def _occurrence(
    *,
    occurrence_id: str = "occ-target",
    session_id: str = "session-target",
    start_at: datetime | None = None,
    status: str = "scheduled",
) -> SessionOccurrence:
    start_at = start_at or _now() + timedelta(days=1)
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id="acad",
        session_id=session_id,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        status=status,  # type: ignore[arg-type]
        scheduled_coach_id="coach-1",
    )


class _FakeMakeups:
    def __init__(self, requests: list[MakeupRequest] | None = None) -> None:
        self.rows: dict[str, MakeupRequest] = {r.request_id: r for r in (requests or [])}
        self.updated: list[MakeupRequest] = []
        self.transition_calls: list[str] = []

    async def get(self, request_id: str) -> MakeupRequest | None:
        return self.rows.get(request_id)

    async def update(self, request: MakeupRequest) -> None:
        self.rows[request.request_id] = request
        self.updated.append(request)

    async def list_by_status(self, status: str | None) -> list[MakeupRequest]:
        rows = list(self.rows.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    async def transition_from_pending(
        self, request_id: str, updates: dict[str, object]
    ) -> MakeupRequest | None:
        """Fake CAS: mirrors the Mongo repo's find_one_and_update filtered on
        {request_id, status: "pending"} — only transitions (and returns) when
        the row is still pending; otherwise returns None."""
        self.transition_calls.append(request_id)
        current = self.rows.get(request_id)
        if current is None or current.status != "pending":
            return None
        updated = current.model_copy(update=updates)
        self.rows[request_id] = updated
        self.updated.append(updated)
        return updated


class _FakeOccurrences:
    def __init__(self, occurrences: list[SessionOccurrence] | None = None) -> None:
        self._occurrences = {o.occurrence_id: o for o in (occurrences or [])}

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        return self._occurrences.get(occurrence_id)


class _FakeEnrollments:
    def __init__(self, enrollments: list[Enrollment] | None = None) -> None:
        self._enrollments = enrollments or []

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.session_id == session_id]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id for e in self._enrollments
        )


class _FakeSessions:
    def __init__(self, sessions=None) -> None:
        self._sessions = {s.session_id: s for s in (sessions or [])}

    async def get(self, session_id: str):
        return self._sessions.get(session_id)

    async def get_many(self, session_ids: list[str]):
        return [s for sid, s in self._sessions.items() if sid in session_ids]


class _FakeOccurrenceRoster:
    def __init__(self, entries: list[OccurrenceRosterEntry] | None = None) -> None:
        self.entries: list[OccurrenceRosterEntry] = list(entries or [])

    async def add(self, entry: OccurrenceRosterEntry) -> None:
        self.entries.append(entry)

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        return [e for e in self.entries if e.occurrence_id == occurrence_id]

    async def exists(self, occurrence_id: str, student_id: str) -> bool:
        return any(
            e.occurrence_id == occurrence_id and e.student_id == student_id for e in self.entries
        )


class _FakeStudents:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._students = {s.student_id: s for s in (students or [])}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._students[sid] for sid in student_ids if sid in self._students]


class _FakeAbsenceNotices:
    def __init__(self, notices: list[AbsenceNotice] | None = None) -> None:
        self._notices = notices or []

    async def list_all(self) -> list[AbsenceNotice]:
        return sorted(self._notices, key=lambda n: n.submitted_at, reverse=True)


def _session(session_id: str = "session-target", capacity: int = 2):
    from backend.v2.contexts.enrollment.domain.models import Session

    return Session(
        session_id=session_id,
        academy_id="acad",
        coach_id="coach-1",
        title="Target session",
        location="Court 1",
        start_at=_now() + timedelta(days=1),
        end_at=_now() + timedelta(days=1, hours=1),
        capacity=capacity,
    )


def _student(student_id: str = "student-1", parent_id: str = "parent-1", full_name="Test Kid"):
    return Student(
        student_id=student_id, academy_id="acad", parent_id=parent_id, full_name=full_name
    )


def _build_approve(
    *,
    makeups: _FakeMakeups | None = None,
    occurrences: _FakeOccurrences | None = None,
    enrollments: _FakeEnrollments | None = None,
    sessions: _FakeSessions | None = None,
    occurrence_roster: _FakeOccurrenceRoster | None = None,
    clock=_now,
) -> tuple[ApproveMakeupRequest, _FakeMakeups, _FakeOccurrenceRoster]:
    makeups = makeups or _FakeMakeups([_pending_request()])
    occurrences = occurrences or _FakeOccurrences([_occurrence()])
    enrollments = enrollments or _FakeEnrollments([])
    sessions = sessions or _FakeSessions([_session()])
    occurrence_roster = occurrence_roster or _FakeOccurrenceRoster()
    use_case = ApproveMakeupRequest(
        makeups=makeups,
        occurrences=occurrences,
        enrollments=enrollments,
        sessions=sessions,
        occurrence_roster=occurrence_roster,
        clock=clock,
    )
    return use_case, makeups, occurrence_roster


# --- ApproveMakeupRequest: NO billing dependency (BILLING SAFETY) -----------


def test_approve_makeup_request_constructor_has_no_billing_parameter() -> None:
    params = inspect.signature(ApproveMakeupRequest.__init__).parameters
    billing_like = {
        name
        for name in params
        if "billing" in name.lower() or "stripe" in name.lower() or "payment" in name.lower()
    }
    assert billing_like == set(), f"ApproveMakeupRequest must not depend on billing: {billing_like}"


@pytest.mark.asyncio
async def test_approve_makeup_request_happy_path_creates_roster_entry() -> None:
    use_case, makeups, roster = _build_approve()

    result = await use_case.execute(
        ApproveMakeupRequestCommand(
            request_id="req-1",
            actor_id="admin-1",
            target_occurrence_id="occ-target",
        )
    )

    assert result.status == "approved"
    assert result.approved_target_occurrence_id == "occ-target"
    assert result.decided_by == "admin-1"
    assert result.decided_at == _now()
    assert len(roster.entries) == 1
    entry = roster.entries[0]
    assert entry.occurrence_id == "occ-target"
    assert entry.student_id == "student-1"
    assert entry.source == "makeup"
    assert entry.origin_request_id == "req-1"
    assert makeups.updated[-1].status == "approved"


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_expired_window() -> None:
    makeups = _FakeMakeups([_pending_request(expires_at=_now() - timedelta(days=1))])
    use_case, _, _ = _build_approve(makeups=makeups)

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_non_pending() -> None:
    makeups = _FakeMakeups([_pending_request(status="denied")])
    use_case, _, _ = _build_approve(makeups=makeups)

    with pytest.raises(MakeupRequestNotPending):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_missing_target_occurrence() -> None:
    use_case, _, _ = _build_approve(occurrences=_FakeOccurrences([]))

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_non_scheduled_target() -> None:
    use_case, _, _ = _build_approve(occurrences=_FakeOccurrences([_occurrence(status="cancelled")]))

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_past_target() -> None:
    use_case, _, _ = _build_approve(
        occurrences=_FakeOccurrences([_occurrence(start_at=_now() - timedelta(hours=1))])
    )

    with pytest.raises(MakeupWindowExpired):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_capacity_full() -> None:
    session = _session(capacity=1)
    enrollments = _FakeEnrollments(
        [
            Enrollment(
                enrollment_id="e1",
                academy_id="acad",
                session_id="session-target",
                student_id="other",
            )
        ]
    )
    use_case, _, _ = _build_approve(sessions=_FakeSessions([session]), enrollments=enrollments)

    with pytest.raises(OccurrenceFull):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


@pytest.mark.asyncio
async def test_approve_makeup_request_counts_existing_roster_entries_toward_capacity() -> None:
    session = _session(capacity=1)
    roster = _FakeOccurrenceRoster(
        [
            OccurrenceRosterEntry(
                entry_id="entry-x",
                academy_id="acad",
                occurrence_id="occ-target",
                student_id="other-student",
                source="makeup",
                origin_request_id="req-other",
                created_at=_now(),
            )
        ]
    )
    use_case, _, _ = _build_approve(sessions=_FakeSessions([session]), occurrence_roster=roster)

    with pytest.raises(OccurrenceFull):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


# --- DenyMakeupRequest -------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_makeup_request_sets_reason_and_decision() -> None:
    makeups = _FakeMakeups([_pending_request()])
    use_case = DenyMakeupRequest(makeups=makeups, clock=_now)

    result = await use_case.execute(
        DenyMakeupRequestCommand(request_id="req-1", actor_id="admin-1", reason="no capacity")
    )

    assert result.status == "denied"
    assert result.denial_reason == "no capacity"
    assert result.decided_by == "admin-1"
    assert result.decided_at == _now()


@pytest.mark.asyncio
async def test_deny_makeup_request_rejects_unknown_request() -> None:
    use_case = DenyMakeupRequest(makeups=_FakeMakeups([]), clock=_now)

    with pytest.raises(MakeupRequestNotFound):
        await use_case.execute(
            DenyMakeupRequestCommand(request_id="req-missing", actor_id="admin-1", reason="x")
        )


@pytest.mark.asyncio
async def test_deny_makeup_request_rejects_non_pending() -> None:
    makeups = _FakeMakeups([_pending_request(status="approved")])
    use_case = DenyMakeupRequest(makeups=makeups, clock=_now)

    with pytest.raises(MakeupRequestNotPending):
        await use_case.execute(
            DenyMakeupRequestCommand(request_id="req-1", actor_id="admin-1", reason="too late")
        )


# --- ListMakeupRequestsForAdmin ----------------------------------------------


@pytest.mark.asyncio
async def test_list_makeup_requests_for_admin_enriches_with_student_name() -> None:
    makeups = _FakeMakeups(
        [
            _pending_request(request_id="req-1", student_id="student-1"),
            _pending_request(request_id="req-2", student_id="student-2"),
        ]
    )
    students = _FakeStudents(
        [
            _student(student_id="student-1", full_name="Alice"),
            _student(student_id="student-2", full_name="Bob"),
        ]
    )
    use_case = ListMakeupRequestsForAdmin(makeups=makeups, students=students)

    rows = await use_case.execute(status=None)

    assert [r.request_id for r in rows] == ["req-1", "req-2"] or [r.request_id for r in rows] == [
        "req-2",
        "req-1",
    ]
    names = {r.request_id: r.student_full_name for r in rows}
    assert names["req-1"] == "Alice"
    assert names["req-2"] == "Bob"


@pytest.mark.asyncio
async def test_list_makeup_requests_for_admin_filters_by_status() -> None:
    makeups = _FakeMakeups(
        [
            _pending_request(request_id="req-pending", status="pending"),
            _pending_request(request_id="req-denied", status="denied"),
        ]
    )
    use_case = ListMakeupRequestsForAdmin(makeups=makeups, students=_FakeStudents([_student()]))

    rows = await use_case.execute(status="pending")

    assert [r.request_id for r in rows] == ["req-pending"]


# --- ListAbsencesForAdmin -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_absences_for_admin_enriches_with_student_name_newest_first() -> None:
    older = AbsenceNotice(
        notice_id="n1",
        academy_id="acad",
        student_id="student-1",
        occurrence_id="occ-1",
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=_now() - timedelta(days=2),
        notice_window_met=True,
    )
    newer = AbsenceNotice(
        notice_id="n2",
        academy_id="acad",
        student_id="student-2",
        occurrence_id="occ-2",
        session_id="session-2",
        submitted_by="parent-2",
        submitted_at=_now() - timedelta(days=1),
        notice_window_met=False,
    )
    notices = _FakeAbsenceNotices([older, newer])
    students = _FakeStudents(
        [
            _student(student_id="student-1", full_name="Alice"),
            _student(student_id="student-2", full_name="Bob"),
        ]
    )
    use_case = ListAbsencesForAdmin(notices=notices, students=students)

    rows = await use_case.execute()

    assert [r.notice_id for r in rows] == ["n2", "n1"]
    assert rows[0].student_full_name == "Bob"
    assert rows[1].student_full_name == "Alice"


@pytest.mark.asyncio
async def test_list_absences_for_admin_missing_student_falls_back_gracefully() -> None:
    notice = AbsenceNotice(
        notice_id="n1",
        academy_id="acad",
        student_id="student-ghost",
        occurrence_id="occ-1",
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=_now(),
        notice_window_met=True,
    )
    use_case = ListAbsencesForAdmin(
        notices=_FakeAbsenceNotices([notice]), students=_FakeStudents([])
    )

    rows = await use_case.execute()

    assert rows[0].student_full_name is None


@pytest.mark.asyncio
async def test_approve_makeup_request_rejects_unknown_request() -> None:
    use_case, _, _ = _build_approve(makeups=_FakeMakeups([]))

    with pytest.raises(MakeupRequestNotFound):
        await use_case.execute(
            ApproveMakeupRequestCommand(
                request_id="req-missing", actor_id="admin-1", target_occurrence_id="occ-target"
            )
        )


# --- Approve/deny double-submit race (TOCTOU CAS guard) ----------------------


@pytest.mark.asyncio
async def test_approve_makeup_request_double_submit_second_call_raises_not_pending() -> None:
    """Simulates two concurrent approvals of the SAME request (double-click /
    two tabs): the initial read-based checks pass for both, but the atomic
    CAS in transition_from_pending can only let one of them through. The
    second call must raise MakeupRequestNotPending and must NOT write a
    second roster entry."""
    makeups = _FakeMakeups([_pending_request()])
    use_case, _, roster = _build_approve(makeups=makeups)

    cmd = ApproveMakeupRequestCommand(
        request_id="req-1", actor_id="admin-1", target_occurrence_id="occ-target"
    )

    result = await use_case.execute(cmd)
    assert result.status == "approved"
    assert len(roster.entries) == 1

    with pytest.raises(MakeupRequestNotPending):
        await use_case.execute(cmd)

    # No duplicate roster entry from the second (losing) call.
    assert len(roster.entries) == 1
    assert len(makeups.updated) == 1


@pytest.mark.asyncio
async def test_deny_makeup_request_double_submit_second_call_raises_not_pending() -> None:
    makeups = _FakeMakeups([_pending_request()])
    use_case = DenyMakeupRequest(makeups=makeups, clock=_now)

    cmd = DenyMakeupRequestCommand(request_id="req-1", actor_id="admin-1", reason="no capacity")

    result = await use_case.execute(cmd)
    assert result.status == "denied"

    with pytest.raises(MakeupRequestNotPending):
        await use_case.execute(cmd)

    assert len(makeups.updated) == 1


# --- Repo-level CAS behavior (exercised against the real Mongo repo via mongomock) --


@pytest.mark.asyncio
async def test_repo_transition_from_pending_wins_once_then_returns_none() -> None:
    """Proves the atomic find_one_and_update CAS: the first call transitions
    the still-pending request and returns it; a second call for the same
    request_id (now no longer pending) returns None instead of re-applying
    the update."""
    mongomock_motor = pytest.importorskip("mongomock_motor")

    from backend.v2.contexts.enrollment.domain.self_service import MakeupRequest
    from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
        MongoMakeupRequestRepository,
    )
    from backend.v2.shared.tenancy import tenant_scope

    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test"]
    repo = MongoMakeupRequestRepository(db)

    with tenant_scope("acad"):
        request = MakeupRequest(
            request_id="req-cas",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-1",
            status="pending",
            expires_at=_now() + timedelta(days=5),
            created_at=_now() - timedelta(days=1),
        )
        await repo.add(request)

        first = await repo.transition_from_pending(
            "req-cas",
            {
                "status": "approved",
                "approved_target_occurrence_id": "occ-target",
                "decided_by": "admin-1",
                "decided_at": _now(),
            },
        )
        assert first is not None
        assert first.status == "approved"
        assert first.approved_target_occurrence_id == "occ-target"

        second = await repo.transition_from_pending(
            "req-cas",
            {
                "status": "approved",
                "approved_target_occurrence_id": "occ-target",
                "decided_by": "admin-2",
                "decided_at": _now(),
            },
        )
        assert second is None

        # The row reflects the winner's update only.
        final = await repo.get("req-cas")
        assert final.decided_by == "admin-1"


@pytest.mark.asyncio
async def test_repo_transition_from_pending_returns_none_for_unknown_request() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")

    from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
        MongoMakeupRequestRepository,
    )
    from backend.v2.shared.tenancy import tenant_scope

    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test"]
    repo = MongoMakeupRequestRepository(db)

    with tenant_scope("acad"):
        result = await repo.transition_from_pending("req-missing", {"status": "approved"})

    assert result is None
