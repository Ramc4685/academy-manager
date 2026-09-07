"""Use-case tests for BulkMarkAttendance with port fakes (issue #672).

The coach roster for an occurrence carries make-up and trial attendees who
have no standing enrollment. "Mark all present" batches every unmarked row,
so the bulk write must accept those rows — and when a row really is
ineligible (paused / withdrawn) the rejection must name it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.coaching.application.ports import (
    AttendanceEligibility,
    OccurrenceDetails,
)
from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkAttendanceEntry,
    BulkMarkAttendance,
    BulkMarkAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    BulkStudentNotEnrolled,
    ConflictAttendanceExists,
)
from backend.v2.contexts.coaching.domain.models import Attendance

FIXED_NOW = datetime(2026, 5, 16, 9, 30, tzinfo=UTC)
OCC = "occ-2026-05-16"


class InMemoryIdempotency:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = value


class FakeAttendanceRepo:
    """Mirrors the unique (occurrence, student) index: a second row for the
    same pair raises, it never overwrites."""

    def __init__(self) -> None:
        self.saved: list[Attendance] = []

    async def save(self, attendance: Attendance) -> None:
        existing = await self.find_existing(attendance.occurrence_id, attendance.student_id)
        if existing is not None:
            raise ConflictAttendanceExists(
                "duplicate",
                occurrence_id=attendance.occurrence_id,
                student_id=attendance.student_id,
                existing_attendance_id=existing.attendance_id,
            )
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

    async def update_status(self, attendance: Attendance) -> None:
        self.saved = [
            attendance if a.attendance_id == attendance.attendance_id else a for a in self.saved
        ]


class FakeOccurrenceLookup:
    def __init__(self, *, template_session_id: str | None = None) -> None:
        self.template_session_id = template_session_id

    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id="sess-1",
            starts_at=FIXED_NOW,
            status="scheduled",
            scheduled_coach_id="coach-1",
            template_session_id=self.template_session_id,
        )


class FakeEnrollmentLookup:
    """Mirrors composition.coaching_lookups.EnrollmentLookupAdapter.

    ``active`` is the set of (session_id, student_id) pairs with an ``active``
    enrollment — a paused or withdrawn student is simply absent from it, the
    same way the Mongo ``status: "active"`` filter drops them. ``roster`` maps
    (occurrence_id, student_id) to an approved one-time source. ``live`` is
    the set of students with an active-or-paused enrollment anywhere in the
    academy (defaults to the students in ``active``): a make-up row is only
    honoured for them, since the row outlives a family's cancel / withdraw.
    """

    def __init__(
        self,
        *,
        active: set[tuple[str, str]] | None = None,
        roster: dict[tuple[str, str], str] | None = None,
        live: set[str] | None = None,
    ) -> None:
        self.active = active or set()
        self.roster = roster or {}
        self.live = live if live is not None else {student_id for _, student_id in self.active}

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return (session_id, student_id) in self.active

    async def attendance_eligibility(
        self,
        *,
        occurrence_id: str,
        session_id: str,
        template_session_id: str | None,
        student_id: str,
    ) -> AttendanceEligibility | None:
        if await self.is_active(session_id, student_id):
            return AttendanceEligibility(source="enrollment")
        if template_session_id and await self.is_active(template_session_id, student_id):
            return AttendanceEligibility(source="enrollment")
        source = self.roster.get((occurrence_id, student_id))
        if source is None:
            return None
        if source == "makeup" and student_id not in self.live:
            return None
        return AttendanceEligibility(source=source)  # type: ignore[arg-type]


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list[Any] = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100):
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


def _cmd(*student_ids: str, mutation_id: str = "bulk-1") -> BulkMarkAttendanceCommand:
    return BulkMarkAttendanceCommand(
        mutation_id=mutation_id,
        occurrence_id=OCC,
        session_id="sess-1",
        entries=[BulkAttendanceEntry(student_id=s, status="present") for s in student_ids],
    )


def _build(**overrides) -> BulkMarkAttendance:
    return BulkMarkAttendance(
        attendance_repo=overrides.pop("attendance_repo", FakeAttendanceRepo()),
        occurrence_lookup=overrides.pop("occurrence_lookup", FakeOccurrenceLookup()),
        enrollment_lookup=overrides.pop(
            "enrollment_lookup", FakeEnrollmentLookup(active={("sess-1", "st1")})
        ),
        outbox=overrides.pop("outbox", FakeOutbox()),
        idempotency_store=overrides.pop("idempotency_store", InMemoryIdempotency()),
        academy_id=lambda: "test-academy",
        clock=lambda: FIXED_NOW,
    )


@pytest.mark.asyncio
async def test_batch_with_enrolled_makeup_and_trial_rows_saves_all_with_sources() -> None:
    # The issue's Saturday scenario: enrolled kids plus one approved make-up
    # (and a trial) on the same "Mark all present" tap.
    repo = FakeAttendanceRepo()
    outbox = FakeOutbox()
    lookup = FakeEnrollmentLookup(
        active={("sess-1", "st1"), ("sess-1", "st2")},
        roster={(OCC, "st-makeup"): "makeup", (OCC, "st-trial"): "trial"},
        live={"st1", "st2", "st-makeup"},
    )
    uc = _build(attendance_repo=repo, outbox=outbox, enrollment_lookup=lookup)

    result = await uc.execute(_cmd("st1", "st2", "st-makeup", "st-trial"), coach_id="coach-1")

    assert [r.student_id for r in result.results] == ["st1", "st2", "st-makeup", "st-trial"]
    sources = {a.student_id: a.entry_source for a in repo.saved}
    assert sources == {
        "st1": "enrollment",
        "st2": "enrollment",
        "st-makeup": "makeup",
        "st-trial": "trial",
    }
    assert {e.payload.student_id: e.payload.entry_source for e in outbox.appended} == sources


@pytest.mark.asyncio
async def test_makeup_entry_resolves_through_template_session_fallback() -> None:
    # Occurrence expanded from a recurring template: enrolled students are
    # active on the template id, the make-up is on the occurrence.
    repo = FakeAttendanceRepo()
    lookup = FakeEnrollmentLookup(
        active={("tmpl-1", "st1")}, roster={(OCC, "st-makeup"): "makeup"}, live={"st1", "st-makeup"}
    )
    uc = _build(
        attendance_repo=repo,
        occurrence_lookup=FakeOccurrenceLookup(template_session_id="tmpl-1"),
        enrollment_lookup=lookup,
    )
    await uc.execute(_cmd("st1", "st-makeup"), coach_id="coach-1")
    assert {a.student_id: a.entry_source for a in repo.saved} == {
        "st1": "enrollment",
        "st-makeup": "makeup",
    }


@pytest.mark.asyncio
async def test_paused_and_withdrawn_rows_fail_the_batch_and_are_named() -> None:
    # st-paused and st-withdrawn have no *active* enrollment and no roster
    # entry; the batch is rejected before any write and the error lists them
    # both — not just the first miss — so the coach UI can say who.
    repo = FakeAttendanceRepo()
    lookup = FakeEnrollmentLookup(
        active={("sess-1", "st1")}, roster={(OCC, "st-makeup"): "makeup"}, live={"st1", "st-makeup"}
    )
    uc = _build(attendance_repo=repo, enrollment_lookup=lookup)

    with pytest.raises(BulkStudentNotEnrolled) as exc_info:
        await uc.execute(_cmd("st1", "st-paused", "st-makeup", "st-withdrawn"), coach_id="coach-1")

    assert exc_info.value.status_code == 422
    assert exc_info.value.details["student_ids"] == ["st-paused", "st-withdrawn"]
    assert exc_info.value.details["occurrence_id"] == OCC
    assert repo.saved == []


@pytest.mark.asyncio
async def test_makeup_for_another_occurrence_is_not_eligible_here() -> None:
    lookup = FakeEnrollmentLookup(
        active={("sess-1", "st1")}, roster={("occ-2026-05-23", "st-makeup"): "makeup"}
    )
    uc = _build(enrollment_lookup=lookup)
    with pytest.raises(BulkStudentNotEnrolled) as exc_info:
        await uc.execute(_cmd("st1", "st-makeup"), coach_id="coach-1")
    assert exc_info.value.details["student_ids"] == ["st-makeup"]


@pytest.mark.asyncio
async def test_makeup_row_of_a_student_with_no_live_enrollment_is_refused() -> None:
    # The family cancelled / withdrew after the make-up was approved; the
    # roster row survived but the student holds no active-or-paused
    # enrollment anywhere. A trial row needs no enrollment at all.
    repo = FakeAttendanceRepo()
    lookup = FakeEnrollmentLookup(
        active={("sess-1", "st1")},
        roster={(OCC, "st-gone"): "makeup", (OCC, "st-trial"): "trial"},
        live={"st1"},
    )
    uc = _build(attendance_repo=repo, enrollment_lookup=lookup)
    with pytest.raises(BulkStudentNotEnrolled) as exc_info:
        await uc.execute(_cmd("st1", "st-gone", "st-trial"), coach_id="coach-1")
    assert exc_info.value.details["student_ids"] == ["st-gone"]
    assert repo.saved == []


@pytest.mark.asyncio
async def test_duplicate_student_ids_still_rejected() -> None:
    uc = _build()
    with pytest.raises(BulkStudentNotEnrolled) as exc_info:
        await uc.execute(_cmd("st1", "st1"), coach_id="coach-1")
    assert "duplicate" in str(exc_info.value)


@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_result_one_save_each() -> None:
    repo = FakeAttendanceRepo()
    lookup = FakeEnrollmentLookup(
        active={("sess-1", "st1")}, roster={(OCC, "st-makeup"): "makeup"}, live={"st1", "st-makeup"}
    )
    uc = _build(attendance_repo=repo, enrollment_lookup=lookup)
    first = await uc.execute(_cmd("st1", "st-makeup"), coach_id="coach-1")
    second = await uc.execute(_cmd("st1", "st-makeup"), coach_id="coach-1")
    assert first == second
    assert len(repo.saved) == 2
