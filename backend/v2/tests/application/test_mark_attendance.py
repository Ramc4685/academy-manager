"""Use-case tests for MarkAttendance with port fakes.

Covers all four rejection paths + idempotency + outbox emission.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendance,
    MarkAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    ConflictAttendanceExists,
    SessionCancelled,
    SessionNotAssigned,
    StudentNotEnrolled,
)
from backend.v2.contexts.coaching.domain.models import Attendance

FIXED_NOW = datetime(2026, 5, 16, 9, 30, tzinfo=UTC)


class InMemoryIdempotency:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = value


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list[Attendance] = []

    async def save(self, attendance: Attendance) -> None:
        self.saved.append(attendance)

    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None:
        for a in self.saved:
            if a.occurrence_id == occurrence_id and a.student_id == student_id:
                return a
        return None

    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None:
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeOccurrenceLookup:
    def __init__(
        self,
        *,
        assigned: bool = True,
        cancelled: bool = False,
        found: bool = True,
        session_id: str = "sess-1",
    ) -> None:
        self.assigned = assigned
        self.cancelled = cancelled
        self.found = found
        self.session_id = session_id

    async def get(self, occurrence_id: str):
        if not self.found:
            return None
        from backend.v2.contexts.coaching.application.ports import OccurrenceDetails

        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id=self.session_id,
            starts_at=FIXED_NOW,
            status="cancelled" if self.cancelled else "scheduled",
            scheduled_coach_id="coach-1" if self.assigned else "other-coach",
            actual_coach_id=None,
            substitute_coach_id=None,
        )


class FakeEnrollmentLookup:
    def __init__(self, active: bool = True) -> None:
        self.active = active

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return self.active


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list[Any] = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100):
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


def _cmd(
    mutation_id: str = "mut-1", student_id: str = "st1", status: str = "present"
) -> MarkAttendanceCommand:
    return MarkAttendanceCommand(
        mutation_id=mutation_id,
        occurrence_id="occ-2026-05-16",
        session_id="sess-1",
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
    )


def _build(**overrides) -> MarkAttendance:
    repo = overrides.pop("attendance_repo", FakeAttendanceRepo())
    occurrences = overrides.pop("occurrence_lookup", FakeOccurrenceLookup())
    enrollments = overrides.pop("enrollment_lookup", FakeEnrollmentLookup())
    outbox = overrides.pop("outbox", FakeOutbox())
    idem = overrides.pop("idempotency_store", InMemoryIdempotency())
    academy_id = overrides.pop("academy_id", lambda: "test-academy")
    return MarkAttendance(
        attendance_repo=repo,
        occurrence_lookup=occurrences,
        enrollment_lookup=enrollments,
        outbox=outbox,
        idempotency_store=idem,
        academy_id=academy_id,
        clock=lambda: FIXED_NOW,
    )


@pytest.mark.asyncio
async def test_happy_path_persists_and_emits_event() -> None:
    repo = FakeAttendanceRepo()
    outbox = FakeOutbox()
    uc = _build(attendance_repo=repo, outbox=outbox)
    result = await uc.execute(_cmd(), coach_id="coach-1")
    assert result.attendance_id == "mut-1"
    assert result.occurrence_id == "occ-2026-05-16"
    assert result.status == "present"
    assert len(repo.saved) == 1
    assert len(outbox.appended) == 1
    event = outbox.appended[0]
    assert event.name == "Coaching.AttendanceMarked"
    assert event.payload.attendance_id == "mut-1"
    assert event.payload.occurrence_id == "occ-2026-05-16"


@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_result_one_save() -> None:
    repo = FakeAttendanceRepo()
    outbox = FakeOutbox()
    uc = _build(attendance_repo=repo, outbox=outbox)
    first = await uc.execute(_cmd(), coach_id="coach-1")
    second = await uc.execute(_cmd(), coach_id="coach-1")
    assert first == second
    assert len(repo.saved) == 1
    assert len(outbox.appended) == 1


@pytest.mark.asyncio
async def test_idempotency_key_is_scoped_by_tenant_and_coach() -> None:
    # #544: client-supplied mutation_id must never be the whole key — the
    # server derives tenant + coach scope so a replayed mutation_id cannot
    # collide across academies or coaches.
    idem = InMemoryIdempotency()
    uc = _build(idempotency_store=idem)
    await uc.execute(_cmd(), coach_id="coach-1")
    assert list(idem.data) == ["mark_attendance:test-academy:coach-1:mut-1"]


@pytest.mark.asyncio
async def test_same_mutation_id_in_other_tenant_is_not_served_from_cache() -> None:
    # #544 failure scenario: coach in academy B replays a mutation_id already
    # cached for academy A. B must get its own write, not A's cached result.
    shared_idem = InMemoryIdempotency()
    repo_a = FakeAttendanceRepo()
    repo_b = FakeAttendanceRepo()
    uc_a = _build(
        attendance_repo=repo_a,
        idempotency_store=shared_idem,
        academy_id=lambda: "academy-a",
    )
    uc_b = _build(
        attendance_repo=repo_b,
        idempotency_store=shared_idem,
        academy_id=lambda: "academy-b",
    )

    await uc_a.execute(_cmd(student_id="st-a"), coach_id="coach-1")
    result_b = await uc_b.execute(_cmd(student_id="st-b"), coach_id="coach-1")

    # B's write actually persisted (not silently suppressed)...
    assert len(repo_b.saved) == 1
    # ...and B's result is B's own data, not academy A's cached result.
    assert result_b.student_id == "st-b"
    assert len(shared_idem.data) == 2


@pytest.mark.asyncio
async def test_same_mutation_id_for_other_coach_is_not_served_from_cache() -> None:
    # A coach cannot pre-claim (or read back) another coach's cached mutation.
    shared_idem = InMemoryIdempotency()
    repo = FakeAttendanceRepo()
    occurrences = FakeOccurrenceLookup()

    async def get_two_coaches(occurrence_id: str):
        details = await occurrences.get(occurrence_id)
        return details.model_copy(update={"actual_coach_id": "coach-2"})

    lookup = FakeOccurrenceLookup()
    lookup.get = get_two_coaches  # type: ignore[method-assign]
    uc = _build(
        attendance_repo=repo,
        idempotency_store=shared_idem,
        occurrence_lookup=lookup,
    )

    await uc.execute(_cmd(), coach_id="coach-1")
    await uc.execute(_cmd(), coach_id="coach-2")

    assert sorted(shared_idem.data) == [
        "mark_attendance:test-academy:coach-1:mut-1",
        "mark_attendance:test-academy:coach-2:mut-1",
    ]


@pytest.mark.asyncio
async def test_session_not_found_raises_not_assigned() -> None:
    uc = _build(occurrence_lookup=FakeOccurrenceLookup(found=False))
    with pytest.raises(SessionNotAssigned):
        await uc.execute(_cmd(), coach_id="coach-1")


@pytest.mark.asyncio
async def test_cancelled_session_rejected() -> None:
    uc = _build(occurrence_lookup=FakeOccurrenceLookup(cancelled=True))
    with pytest.raises(SessionCancelled):
        await uc.execute(_cmd(), coach_id="coach-1")


@pytest.mark.asyncio
async def test_unassigned_coach_rejected() -> None:
    uc = _build(occurrence_lookup=FakeOccurrenceLookup(assigned=False))
    with pytest.raises(SessionNotAssigned):
        await uc.execute(_cmd(), coach_id="coach-1")


@pytest.mark.asyncio
async def test_unenrolled_student_rejected() -> None:
    uc = _build(enrollment_lookup=FakeEnrollmentLookup(active=False))
    with pytest.raises(StudentNotEnrolled):
        await uc.execute(_cmd(), coach_id="coach-1")


@pytest.mark.asyncio
async def test_conflict_when_different_mutation_id_exists() -> None:
    repo = FakeAttendanceRepo()
    uc = _build(attendance_repo=repo)
    await uc.execute(_cmd(mutation_id="mut-1"), coach_id="coach-1")
    # Different mutation hits same (session, student) — must conflict.
    with pytest.raises(ConflictAttendanceExists):
        await uc.execute(_cmd(mutation_id="mut-2"), coach_id="coach-1")


@pytest.mark.asyncio
async def test_same_student_can_be_marked_again_for_different_occurrence() -> None:
    repo = FakeAttendanceRepo()
    uc = _build(attendance_repo=repo)

    await uc.execute(_cmd(mutation_id="mut-1"), coach_id="coach-1")
    await uc.execute(
        _cmd(mutation_id="mut-2").model_copy(update={"occurrence_id": "occ-2026-05-23"}),
        coach_id="coach-1",
    )

    assert [row.occurrence_id for row in repo.saved] == ["occ-2026-05-16", "occ-2026-05-23"]
