"""EditRosterAdd failure paths — issue #610 (admin add-to-roster returns 500).

The reported symptom was a bare "Internal Server Error" banner plus a session
whose roster never grew while its seat count kept climbing. Two defects
produced that pair:

1. ``try_reserve_seat`` incremented ``reserved_seats`` *before* any of the
   three writes that follow it, and nothing released the seat when one of
   those writes blew up. Every failed add permanently burned a seat, and the
   drift is one-way (``release_seat`` has a ``> 0`` floor), so it never
   self-heals.
2. The student write was a full-model ``$set`` upsert, so re-adding an
   existing student nulled their profile fields — including
   ``student_user_id``, silently breaking that student's login.

These tests pin the compensating release, the duplicate pre-check, the
diagnosis of a failed reserve, and the narrowed student write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    EditRosterAdd,
    EditRosterAddCommand,
    ResumeEnrollment,
)
from backend.v2.contexts.enrollment.domain.errors import (
    CapacityExceeded,
    SeatCounterDrift,
    SessionNotEnrollable,
    SessionNotFound,
    StudentAlreadyOnRoster,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student

ACADEMY = "acad-1"


def _session(
    *,
    session_id: str = "sess-1",
    capacity: int = 10,
    status: str = "scheduled",
) -> Session:
    return Session(
        session_id=session_id,
        academy_id=ACADEMY,
        coach_id="coach-1",
        title="Beginner Badminton",
        location="Court 1",
        start_at=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
        capacity=capacity,
        status=status,  # type: ignore[arg-type]
    )


@dataclass
class FakeSessions:
    """SessionWriter fake that models `reserved_seats` as a real counter."""

    sessions: dict[str, Session] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)
    reserve_calls: list[str] = field(default_factory=list)
    release_calls: list[str] = field(default_factory=list)
    release_raises: BaseException | None = None

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserve_calls.append(session_id)
        session = self.sessions.get(session_id)
        if session is None or session.status not in {"scheduled", "active", "open"}:
            return False
        if self.reserved.get(session_id, 0) >= session.capacity:
            return False
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.release_calls.append(session_id)
        if self.release_raises is not None:
            raise self.release_raises
        # Mongo's release has a `> 0` floor; mirror it so the fake cannot go
        # negative and hide a double-release bug.
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)


@dataclass
class FakeEnrollments:
    rows: dict[str, Enrollment] = field(default_factory=dict)
    create_raises: BaseException | None = None

    async def create(self, enrollment: Enrollment) -> None:
        if self.create_raises is not None:
            raise self.create_raises
        self.rows[enrollment.enrollment_id] = enrollment

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.session_id == session_id and row.student_id == student_id
            ),
            None,
        )

    async def count_active_for_session(self, session_id: str) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.session_id == session_id and row.status == "active"
        )

    async def update_status(self, enrollment_id: str, status: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(update={"status": status})


@dataclass
class FakeStudents:
    """StudentWriter fake recording exactly which fields each call writes."""

    rows: dict[str, Student] = field(default_factory=dict)
    ensure_calls: list[Student] = field(default_factory=list)
    upsert_calls: list[Student] = field(default_factory=list)
    ensure_raises: BaseException | None = None

    async def upsert(self, student: Student) -> None:
        self.upsert_calls.append(student)
        self.rows[student.student_id] = student

    async def ensure_exists(self, student: Student) -> bool:
        self.ensure_calls.append(student)
        if self.ensure_raises is not None:
            raise self.ensure_raises
        if student.student_id in self.rows:
            # Insert-only semantics: an existing row is left untouched.
            return False
        self.rows[student.student_id] = student
        return True


@dataclass
class FakeEvents:
    rows: list[Any] = field(default_factory=list)
    record_raises: BaseException | None = None

    async def record(self, event: Any) -> None:
        if self.record_raises is not None:
            raise self.record_raises
        self.rows.append(event)


def _use_case(
    sessions: FakeSessions,
    enrollments: FakeEnrollments,
    students: FakeStudents,
    events: FakeEvents | None = None,
    *,
    with_resume: bool = True,
) -> EditRosterAdd:
    resume = (
        ResumeEnrollment(
            enrollments=enrollments,  # type: ignore[arg-type]
            sessions=sessions,  # type: ignore[arg-type]
            enrollment_events=events,  # type: ignore[arg-type]
        )
        if with_resume
        else None
    )
    return EditRosterAdd(
        sessions=sessions,  # type: ignore[arg-type]
        enrollments=enrollments,  # type: ignore[arg-type]
        students=students,  # type: ignore[arg-type]
        enrollment_events=events,  # type: ignore[arg-type]
        resume=resume,
        academy_id=ACADEMY,
    )


def _cmd(student_id: str = "st-1", full_name: str = "Alice Nguyen") -> EditRosterAddCommand:
    return EditRosterAddCommand(
        session_id="sess-1",
        student_id=student_id,
        parent_id="par-1",
        full_name=full_name,
        actor_id="admin-1",
    )


def _seeded() -> tuple[FakeSessions, FakeEnrollments, FakeStudents]:
    sessions = FakeSessions(sessions={"sess-1": _session()})
    return sessions, FakeEnrollments(), FakeStudents()


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_reserves_exactly_one_seat_and_creates_the_row() -> None:
    sessions, enrollments, students = _seeded()
    uc = _use_case(sessions, enrollments, students)

    enrollment = await uc.execute(_cmd())

    assert enrollment.status == "active"
    assert enrollment.academy_id == ACADEMY
    assert sessions.reserved["sess-1"] == 1
    assert sessions.release_calls == []
    assert list(enrollments.rows) == [enrollment.enrollment_id]


# --- (a) duplicate add -> 409, seat count unchanged -------------------------


@pytest.mark.asyncio
async def test_existing_active_enrollment_is_refused_without_reserving() -> None:
    sessions, enrollments, students = _seeded()
    enrollments.rows["enr-existing"] = Enrollment(
        enrollment_id="enr-existing",
        academy_id=ACADEMY,
        session_id="sess-1",
        student_id="st-1",
        status="active",
    )
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(StudentAlreadyOnRoster) as exc:
        await uc.execute(_cmd(full_name="Alice Nguyen"))

    # The message must name the student so the admin knows who to look at.
    assert "Alice Nguyen" in exc.value.message
    assert exc.value.details["enrollment_id"] == "enr-existing"
    assert exc.value.status_code == 409
    # No seat was burned: the pre-check runs before the reserve.
    assert sessions.reserve_calls == []
    assert sessions.reserved.get("sess-1", 0) == 0
    assert len(enrollments.rows) == 1


def _seed_paused(enrollments: FakeEnrollments) -> None:
    enrollments.rows["enr-paused"] = Enrollment(
        enrollment_id="enr-paused",
        academy_id=ACADEMY,
        session_id="sess-1",
        student_id="st-1",
        status="paused",
    )


@pytest.mark.asyncio
async def test_existing_paused_enrollment_is_resumed_in_place() -> None:
    """Re-adding a paused student is a resume, not a duplicate and not a 409.

    Prod 2026-09-03: a student paused in July was hidden from the roster read
    yet blocked "Add to roster" with "already on this roster (paused)" — a
    dead end with no visible row to act on.
    """
    sessions, enrollments, students = _seeded()
    _seed_paused(enrollments)
    events = FakeEvents()
    uc = _use_case(sessions, enrollments, students, events)

    out = await uc.execute(_cmd())

    assert out.enrollment_id == "enr-paused"
    assert out.status == "active"
    assert enrollments.rows["enr-paused"].status == "active"
    assert list(enrollments.rows) == ["enr-paused"], "no second row next to the paused one"
    assert sessions.reserve_calls == ["sess-1"], "resume re-reserves exactly one seat"
    assert sessions.reserved["sess-1"] == 1
    assert [e.event_type for e in events.rows] == ["resumed"]
    assert students.ensure_calls == [], "no student write on a resume"


@pytest.mark.asyncio
async def test_existing_paused_enrollment_is_refused_when_resume_is_unwired() -> None:
    sessions, enrollments, students = _seeded()
    _seed_paused(enrollments)
    uc = _use_case(sessions, enrollments, students, with_resume=False)

    with pytest.raises(StudentAlreadyOnRoster) as exc:
        await uc.execute(_cmd())

    assert "Use Resume on the roster" in str(exc.value)
    assert sessions.reserve_calls == []


@pytest.mark.asyncio
async def test_cancelled_enrollment_does_not_block_a_re_add() -> None:
    sessions, enrollments, students = _seeded()
    enrollments.rows["enr-old"] = Enrollment(
        enrollment_id="enr-old",
        academy_id=ACADEMY,
        session_id="sess-1",
        student_id="st-1",
        status="cancelled",
    )
    uc = _use_case(sessions, enrollments, students)

    enrollment = await uc.execute(_cmd())

    assert enrollment.enrollment_id != "enr-old"
    assert sessions.reserved["sess-1"] == 1


@pytest.mark.asyncio
async def test_duplicate_key_from_the_student_write_releases_the_seat() -> None:
    """The backstop for the real prod 500: a global `student_id_unique` index.

    The tenant-scoped upsert filter missed a students doc belonging to another
    academy, degraded to an insert, and E11000'd. The seat had already been
    reserved.
    """
    sessions, enrollments, students = _seeded()
    students.ensure_raises = DuplicateKeyError("E11000 dup key: { student_id: 'st-1' }")
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(StudentAlreadyOnRoster):
        await uc.execute(_cmd())

    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved["sess-1"] == 0


@pytest.mark.asyncio
async def test_duplicate_key_from_enrollment_create_releases_the_seat_and_409s() -> None:
    sessions, enrollments, students = _seeded()
    enrollments.create_raises = DuplicateKeyError("E11000 dup key")
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(StudentAlreadyOnRoster):
        await uc.execute(_cmd())

    assert sessions.reserved["sess-1"] == 0


# --- (b) a write failure after reserve -> seat released ---------------------


@pytest.mark.asyncio
async def test_arbitrary_exception_after_reserve_releases_the_seat() -> None:
    sessions, enrollments, students = _seeded()
    enrollments.create_raises = RuntimeError("mongo is down")
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(RuntimeError, match="mongo is down"):
        await uc.execute(_cmd())

    assert sessions.release_calls == ["sess-1"]
    assert sessions.reserved["sess-1"] == 0


@pytest.mark.asyncio
async def test_lifecycle_event_failure_keeps_the_add_and_the_seat() -> None:
    """The enrollment row is the point of no return.

    The audit event is written after it, so a failure there must not run the
    compensation: releasing the seat under a live enrollment leaves the seat
    counter one *below* the roster, and the session then admits a student past
    capacity. The add succeeded, so it is also not an error for the admin.
    """
    sessions, enrollments, students = _seeded()
    events = FakeEvents(record_raises=RuntimeError("event store down"))
    uc = _use_case(sessions, enrollments, students, events)

    enrollment = await uc.execute(_cmd())

    assert enrollment.status == "active"
    assert sessions.release_calls == []
    assert sessions.reserved["sess-1"] == 1


@pytest.mark.asyncio
async def test_release_failure_does_not_mask_the_original_error() -> None:
    sessions, enrollments, students = _seeded()
    enrollments.create_raises = RuntimeError("the real problem")
    sessions.release_raises = RuntimeError("release also broke")
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(RuntimeError, match="the real problem"):
        await uc.execute(_cmd())

    assert sessions.release_calls == ["sess-1"]


# --- (c) capacity genuinely full -> 409 with the real numbers ---------------


@pytest.mark.asyncio
async def test_capacity_message_carries_real_numbers() -> None:
    sessions = FakeSessions(sessions={"sess-1": _session(capacity=2)})
    enrollments = FakeEnrollments()
    students = FakeStudents()
    for index in range(2):
        enrollments.rows[f"enr-{index}"] = Enrollment(
            enrollment_id=f"enr-{index}",
            academy_id=ACADEMY,
            session_id="sess-1",
            student_id=f"st-other-{index}",
            status="active",
        )
    sessions.reserved["sess-1"] = 2
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(CapacityExceeded) as exc:
        await uc.execute(_cmd())

    assert exc.value.status_code == 409
    assert exc.value.details["capacity"] == 2
    assert exc.value.details["active_enrollments"] == 2
    assert "2" in exc.value.message
    assert "full" in exc.value.message.lower()
    # A refused reserve must not have moved the counter.
    assert sessions.reserved["sess-1"] == 2
    assert sessions.release_calls == []


@pytest.mark.asyncio
async def test_seat_counter_drift_is_reported_not_reconciled() -> None:
    """Reserve refused while the roster is demonstrably under capacity.

    Do NOT silently reconcile: `reserved_seats` is legitimately ahead of the
    enrollment rows while a parent checkout is in flight, so a repair write
    here would clobber a live reservation and oversell the session.
    """
    sessions = FakeSessions(sessions={"sess-1": _session(capacity=5)})
    sessions.reserved["sess-1"] = 5  # counter says full, roster says empty
    enrollments = FakeEnrollments()
    students = FakeStudents()
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(SeatCounterDrift) as exc:
        await uc.execute(_cmd())

    assert exc.value.details["capacity"] == 5
    assert exc.value.details["active_enrollments"] == 0
    assert sessions.reserved["sess-1"] == 5  # untouched
    assert sessions.release_calls == []


@pytest.mark.asyncio
async def test_non_enrollable_session_status_is_not_reported_as_full() -> None:
    sessions = FakeSessions(sessions={"sess-1": _session(status="cancelled")})
    enrollments = FakeEnrollments()
    students = FakeStudents()
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(SessionNotEnrollable) as exc:
        await uc.execute(_cmd())

    assert exc.value.details["status"] == "cancelled"


@pytest.mark.asyncio
async def test_missing_session_is_404_not_full() -> None:
    sessions = FakeSessions()
    enrollments = FakeEnrollments()
    students = FakeStudents()
    uc = _use_case(sessions, enrollments, students)

    with pytest.raises(SessionNotFound) as exc:
        await uc.execute(_cmd())

    assert exc.value.status_code == 404


# --- (d) an existing student's profile survives a re-add --------------------


@pytest.mark.asyncio
async def test_student_write_never_clobbers_profile_fields() -> None:
    """The roster path owns no fields on an existing student.

    It must go through the insert-only `ensure_exists`, never the full-model
    `upsert` that registration approval uses.
    """
    sessions, enrollments, students = _seeded()
    existing = Student(
        student_id="st-1",
        academy_id=ACADEMY,
        parent_id="par-1",
        full_name="Alice Nguyen",
        date_of_birth="2014-03-02",
        emergency_contact_name="Bao Nguyen",
        emergency_contact_phone="+1-555-0100",
        medical_notes="peanut allergy",
        student_user_id="usr-alice",
    )
    students.rows["st-1"] = existing
    uc = _use_case(sessions, enrollments, students)

    await uc.execute(_cmd(full_name="Alice N."))

    assert students.upsert_calls == [], "roster add must not use the full-model upsert"
    assert students.rows["st-1"] == existing, "existing profile must survive untouched"
    # ...including the login link, whose loss silently locks the student out.
    assert students.rows["st-1"].student_user_id == "usr-alice"


@pytest.mark.asyncio
async def test_a_brand_new_student_is_still_created() -> None:
    sessions, enrollments, students = _seeded()
    uc = _use_case(sessions, enrollments, students)

    await uc.execute(_cmd(student_id="st-new", full_name="New Kid"))

    assert students.rows["st-new"].full_name == "New Kid"
    assert students.rows["st-new"].academy_id == ACADEMY


# --- tenancy ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_academy_id_may_be_a_request_time_provider() -> None:
    """#532-class trap: a boot-frozen tenant must not leak into the write."""
    sessions, enrollments, students = _seeded()
    uc = EditRosterAdd(
        sessions=sessions,  # type: ignore[arg-type]
        enrollments=enrollments,  # type: ignore[arg-type]
        students=students,  # type: ignore[arg-type]
        academy_id=lambda: "acad-from-request",
    )

    enrollment = await uc.execute(_cmd(student_id="st-2"))

    assert enrollment.academy_id == "acad-from-request"
    assert students.rows["st-2"].academy_id == "acad-from-request"


# --- #613 welcome email trigger ---------------------------------------------


class _RecordingNotifier:
    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    async def send_welcome(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises


@pytest.mark.asyncio
async def test_roster_add_sends_the_welcome_email() -> None:
    sessions = FakeSessions(sessions={"sess-1": _session()})
    enrollments = FakeEnrollments()
    students = FakeStudents()
    notifier = _RecordingNotifier()
    uc = EditRosterAdd(
        sessions=sessions,  # type: ignore[arg-type]
        enrollments=enrollments,  # type: ignore[arg-type]
        students=students,  # type: ignore[arg-type]
        academy_id=ACADEMY,
        welcome_notifier=notifier,  # type: ignore[arg-type]
    )

    await uc.execute(_cmd())

    assert notifier.calls == [
        {
            "session_id": "sess-1",
            "student_name": "Alice Nguyen",
            "parent_user_id": "par-1",
        }
    ]


@pytest.mark.asyncio
async def test_roster_add_succeeds_when_the_welcome_email_fails() -> None:
    """Catch/log/continue, by design.

    The seat is reserved and the roster row exists by the time the email is
    attempted. Surfacing a mail failure as an add failure would show the admin
    an error for work that succeeded — and the retry would then trip the
    duplicate guard.
    """
    sessions = FakeSessions(sessions={"sess-1": _session()})
    enrollments = FakeEnrollments()
    students = FakeStudents()
    notifier = _RecordingNotifier(raises=RuntimeError("resend is down"))
    uc = EditRosterAdd(
        sessions=sessions,  # type: ignore[arg-type]
        enrollments=enrollments,  # type: ignore[arg-type]
        students=students,  # type: ignore[arg-type]
        academy_id=ACADEMY,
        welcome_notifier=notifier,  # type: ignore[arg-type]
    )

    enrollment = await uc.execute(_cmd())

    assert enrollment.status == "active"
    assert enrollments.rows[enrollment.enrollment_id].status == "active"
    # The failure must not have been "compensated" into a released seat: the
    # student really is on the roster.
    assert sessions.release_calls == []
