"""Interface-test fixtures.

Builds a FastAPI app with the coach router and an in-memory test
composition so we never spin up Mongo. Auth is injected via FastAPI's
dependency override.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    PreviewStudentSessionTypeMove,
)
from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkMarkAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.application.use_cases.mark_coach_attendance import (
    MarkCoachAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.session_feedback import (
    CreateSessionFeedback,
    ListSessionFeedback,
)
from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlan,
    CreateProgressNote,
    ListLessonPlans,
    ListProgressNotes,
)
from backend.v2.contexts.coaching.domain.models import Attendance, CoachAttendance
from backend.v2.contexts.enrollment.application.use_cases.coach_roster_writes import (
    CoachAddStudentToRoster,
    CoachRemoveStudentFromRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    GetOccurrenceRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    ListCoachOccurrencesForDate,
    ListCoachUpcomingOccurrences,
)
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

# --- in-memory fakes ---


class FakeSessionQuery:
    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        return [
            s for s in self._sessions if s.coach_id == coach_id and s.start_at.date() == on_date
        ]

    async def get(self, session_id: str) -> Session | None:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        return None

    async def for_coach(self, coach_id: str) -> list[Session]:
        return [s for s in self._sessions if s.coach_id == coach_id]

    async def assigned_session_ids_for_coach(self, coach_id: str) -> list[str]:
        return sorted({s.session_id for s in self._sessions if s.coach_id == coach_id})


class FakeEnrollmentQuery:
    def __init__(self, enrollments: list[Enrollment]) -> None:
        self._enrollments = enrollments

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.session_id == session_id and e.status == "active"]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self._enrollments
        )


class FakeStudentQuery:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._by_id[s] for s in student_ids if s in self._by_id]


class FakeOccurrenceQuery:
    def __init__(self, occurrences: list[SessionOccurrence]) -> None:
        self._occurrences = occurrences

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        for occurrence in self._occurrences:
            if occurrence.occurrence_id == occurrence_id:
                return occurrence
        return None

    async def list_for_coach_on_date(
        self, *, coach_id: str, on_date: date
    ) -> list[SessionOccurrence]:
        return [
            occurrence
            for occurrence in self._occurrences
            if occurrence.start_at.date() == on_date
            and occurrence.status != "cancelled"
            and coach_id
            in {
                occurrence.scheduled_coach_id,
                occurrence.actual_coach_id,
                occurrence.substitute_coach_id,
            }
        ]

    async def list_for_coach_upcoming(
        self,
        *,
        coach_id: str,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[SessionOccurrence]:
        start_at = now or _now()
        rows = [
            occurrence
            for occurrence in self._occurrences
            if occurrence.start_at >= start_at
            and occurrence.status != "cancelled"
            and coach_id
            in {
                occurrence.scheduled_coach_id,
                occurrence.actual_coach_id,
                occurrence.substitute_coach_id,
            }
        ]
        return sorted(rows, key=lambda occurrence: occurrence.start_at)[:limit]


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list = []

    async def save(self, attendance) -> None:
        self.saved.append(attendance)

    async def find_existing(self, occurrence_id, student_id):
        for a in self.saved:
            if a.occurrence_id == occurrence_id and a.student_id == student_id:
                return a
        return None

    async def find_by_attendance_id(self, attendance_id):
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None

    async def update_status(self, attendance) -> None:
        self.saved = [
            attendance if a.attendance_id == attendance.attendance_id else a for a in self.saved
        ]

    async def list_for_occurrence(self, occurrence_id):
        return [a for a in self.saved if a.occurrence_id == occurrence_id]


class FakeCoachingNotesRepo:
    def __init__(self) -> None:
        self.plans: list = []
        self.notes: list = []

    async def add_lesson_plan(self, plan):
        self.plans.append(plan)

    async def list_lesson_plans(self, session_id, coach_id):
        return [p for p in self.plans if p.session_id == session_id and p.coach_id == coach_id]

    async def add_progress_note(self, note):
        self.notes.append(note)

    async def list_progress_notes(self, session_id, coach_id):
        return [n for n in self.notes if n.session_id == session_id and n.coach_id == coach_id]

    async def find_by_attendance_id(self, attendance_id):
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeFeedbackRepo:
    def __init__(self) -> None:
        self.saved: list = []

    async def save(self, feedback) -> None:
        self.saved.append(feedback)

    async def list_for_session(self, session_id: str, *, limit: int = 100) -> list:
        return [f for f in self.saved if f.session_id == session_id][:limit]

    async def list_for_student(self, student_id: str, *, limit: int = 100) -> list:
        return [f for f in self.saved if f.student_id == student_id][:limit]


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100):
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def put(self, key: str, value) -> None:
        self.data[key] = value


class FakeCoachEnrollmentWriter:
    """Combined EnrollmentWriter + minimal SessionWriter for coach roster tests."""

    def __init__(self, enrollments: list[Enrollment], sessions: list[Session]) -> None:
        self._enrollments: dict[str, Enrollment] = {e.enrollment_id: e for e in enrollments}
        self._sessions: dict[str, Session] = {s.session_id: s for s in sessions}
        self._reserved: dict[str, int] = {}

    # --- SessionWriter ---
    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        s = self._sessions.get(session_id)
        if s is None or s.status != "scheduled":
            return False
        taken = self._reserved.get(session_id, 0)
        if taken >= s.capacity:
            return False
        self._reserved[session_id] = taken + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self._reserved[session_id] = max(0, self._reserved.get(session_id, 0) - 1)

    async def update_status(self, session_id: str, status: str) -> None:
        s = self._sessions.get(session_id)
        if s is not None:
            self._sessions[session_id] = s.model_copy(update={"status": status})

    async def create(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    async def update(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    # --- EnrollmentWriter ---
    async def create_enrollment(self, enrollment: Enrollment) -> None:
        self._enrollments[enrollment.enrollment_id] = enrollment

    async def update_enrollment_status(self, enrollment_id: str, status: str) -> None:
        e = self._enrollments.get(enrollment_id)
        if e is not None:
            self._enrollments[enrollment_id] = e.model_copy(update={"status": status})

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (
                e
                for e in self._enrollments.values()
                if e.session_id == session_id and e.student_id == student_id
            ),
            None,
        )


class _EnrollmentWriterAdapter:
    """Adapts FakeCoachEnrollmentWriter to the EnrollmentWriter protocol."""

    def __init__(self, store: FakeCoachEnrollmentWriter) -> None:
        self._store = store

    async def create(self, enrollment: Enrollment) -> None:
        await self._store.create_enrollment(enrollment)

    async def update_status(self, enrollment_id: str, status: str) -> None:
        await self._store.update_enrollment_status(enrollment_id, status)

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        pass

    async def update_amount_cents(self, enrollment_id: str, amount_cents: int | None) -> None:
        pass

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self._store._enrollments.get(enrollment_id)

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return await self._store.find_for_session_student(session_id, student_id)


class FakeCoachStudentWriter:
    def __init__(self) -> None:
        self._students: dict[str, Student] = {}

    async def upsert(self, student: Student) -> None:
        self._students[student.student_id] = student

    async def ensure_exists(self, student: Student) -> bool:
        if student.student_id in self._students:
            return False
        self._students[student.student_id] = student
        return True


class FakeAbsenceNoticeQuery:
    """In-memory AbsenceNotice reads for coach-today's expected_absence flag."""

    def __init__(self, notices: list | None = None) -> None:
        self._notices = notices or []

    async def list_for_occurrence(self, occurrence_id: str):
        return [n for n in self._notices if n.occurrence_id == occurrence_id]


class FakeOccurrenceRosterQuery:
    """In-memory one-time (makeup/trial) occurrence roster entries."""

    def __init__(self, entries: list[OccurrenceRosterEntry] | None = None) -> None:
        self._entries = entries or []

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]:
        return [e for e in self._entries if e.occurrence_id == occurrence_id]

    async def exists(self, occurrence_id: str, student_id: str) -> bool:
        return any(
            e.occurrence_id == occurrence_id and e.student_id == student_id for e in self._entries
        )


# --- seed data ---


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seed():
    sessions = [
        Session(
            session_id="s-today-1",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Junior A",
            location="Court 1",
            start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
            capacity=8,
            status="scheduled",
            timezone="America/Chicago",
        ),
        Session(
            session_id="s-today-2",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Adult B",
            location="Court 2",
            start_at=datetime(2026, 5, 16, 18, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 19, 30, tzinfo=UTC),
            capacity=10,
            status="scheduled",
            timezone="America/Chicago",
        ),
        Session(
            session_id="s-other-coach",
            academy_id="test-academy",
            coach_id="coach-2",
            title="Not mine",
            location="Court 3",
            start_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 13, 0, tzinfo=UTC),
            capacity=4,
            status="scheduled",
            timezone="America/Chicago",
        ),
    ]
    enrollments = [
        Enrollment(
            enrollment_id="e1",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st1",
            status="active",
        ),
        Enrollment(
            enrollment_id="e2",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st2",
            status="active",
        ),
    ]
    students = [
        Student(student_id="st1", academy_id="test-academy", parent_id="p1", full_name="Alice"),
        Student(student_id="st2", academy_id="test-academy", parent_id="p2", full_name="Bob"),
    ]
    occurrences = [
        SessionOccurrence(
            occurrence_id="occ-today-1",
            academy_id="test-academy",
            session_id="occurrence-session-1",
            template_session_id="s-today-1",
            start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
            status="scheduled",
            scheduled_coach_id="coach-1",
        ),
        SessionOccurrence(
            occurrence_id="occ-today-2",
            academy_id="test-academy",
            session_id="occurrence-session-2",
            template_session_id="s-today-2",
            start_at=datetime(2026, 5, 16, 18, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 19, 30, tzinfo=UTC),
            status="scheduled",
            scheduled_coach_id="coach-2",
            actual_coach_id="coach-1",
        ),
        SessionOccurrence(
            occurrence_id="occ-other-coach",
            academy_id="test-academy",
            session_id="occurrence-session-3",
            template_session_id="s-other-coach",
            start_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 13, 0, tzinfo=UTC),
            status="scheduled",
            scheduled_coach_id="coach-2",
        ),
    ]
    return {
        "sessions": sessions,
        "enrollments": enrollments,
        "students": students,
        "occurrences": occurrences,
        # Populated only by tests exercising expected-absence flags / one-time
        # roster entries (Task 3); empty by default so existing scenarios
        # (including the coach-today golden master) are unaffected.
        "absence_notices": [],
        "occurrence_roster_entries": [],
    }


def _coach_claims() -> AuthClaims:
    return AuthClaims(
        user_id="coach-1",
        email="coach1@example.com",
        academy_id="test-academy",
        roles=("coach",),
    )


def _parent_claims() -> AuthClaims:
    return AuthClaims(
        user_id="p1",
        email="parent@example.com",
        academy_id="test-academy",
        roles=("parent",),
    )


def _admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="adm",
        email="admin@example.com",
        academy_id="test-academy",
        roles=("admin",),
    )


async def _async_none(*_args, **_kwargs):
    return None


def _build_use_cases(seed_data) -> CoachUseCases:
    sessions = FakeSessionQuery(seed_data["sessions"])
    enrollments = FakeEnrollmentQuery(seed_data["enrollments"])
    students = FakeStudentQuery(seed_data["students"])
    occurrences = FakeOccurrenceQuery(seed_data["occurrences"])
    absence_notices = FakeAbsenceNoticeQuery(seed_data.get("absence_notices"))
    occurrence_roster = FakeOccurrenceRosterQuery(seed_data.get("occurrence_roster_entries"))
    _coach_messages_repo = FakeMessageRepo()

    class _CoachMessagesVisibility:
        """Mirrors composition/coach.py: sessions assigned to this coach (#614)."""

        async def _visible_session_ids(self, coach_id):
            # Assignment, not the upcoming window: `for_coach` filters
            # `start_at >= now`, which hides every recurring series whose
            # stored `start_at` has passed.
            return await sessions.assigned_session_ids_for_coach(coach_id)

        async def list_messages(self, coach_id):
            return await _coach_messages_repo.for_recipient(
                coach_id, visible_session_ids=await self._visible_session_ids(coach_id)
            )

        async def mark_message_read(self, message_id, user_id):
            await _coach_messages_repo.mark_read(
                message_id, user_id, visible_session_ids=await self._visible_session_ids(user_id)
            )

    _coach_messages_visible = _CoachMessagesVisibility()

    # Adapters wiring coach lookups to enrollment queries.
    class _SL:
        async def is_coach_assigned(self, coach_id, sid, on_date=None):
            s = await sessions.get(sid)
            if s is None or s.coach_id != coach_id:
                return False
            return on_date is None or s.start_at.date() == on_date

        async def is_cancelled(self, sid):
            s = await sessions.get(sid)
            return s is not None and s.status == "cancelled"

        async def session_date(self, sid):
            s = await sessions.get(sid)
            return s.start_at.date() if s else None

    class _OL:
        async def get(self, occurrence_id):
            occurrence = await occurrences.get(occurrence_id)
            if occurrence is None:
                return None
            return OccurrenceDetails(
                occurrence_id=occurrence_id,
                session_id=occurrence.session_id,
                starts_at=occurrence.start_at,
                status=occurrence.status,
                scheduled_coach_id=occurrence.scheduled_coach_id,
                actual_coach_id=occurrence.actual_coach_id,
                substitute_coach_id=occurrence.substitute_coach_id,
                template_session_id=occurrence.template_session_id,
            )

    class _EL:
        async def is_active(self, sid, student_id):
            return await enrollments.is_active(sid, student_id)

    async def _dashboard(_coach_id):
        return {
            "active_student_count": 2,
            "sessions_today": 2,
            "attendance_percentage": 0.0,
            "expected_cut_cents": 0,
            "marked_attendance_count": 0,
        }

    notes = FakeCoachingNotesRepo()
    _feedback_repo = FakeFeedbackRepo()
    session_lookup = _SL()
    rw_store = FakeCoachEnrollmentWriter(seed_data["enrollments"], seed_data["sessions"])
    enrollment_writer = _EnrollmentWriterAdapter(rw_store)
    student_writer = FakeCoachStudentWriter()
    _attendance_repo = FakeAttendanceRepo()
    _occurrence_lookup = _OL()
    _enrollment_lookup = _EL()
    _outbox = FakeOutbox()
    _idempotency_store = FakeIdempotencyStore()

    # Minimal billing stubs (not exercised by existing coach tests)
    class _StubBillingEnrollmentRepo:
        async def save(self, e):
            pass

        async def get(self, eid):
            return None

        async def list_for_student(self, sid):
            return []

        async def list_for_parent(self, pid):
            return []

        async def get_by_stripe_subscription(self, sub):
            return None

    class _StubSessionTypeRepo:
        async def save(self, st):
            pass

        async def get(self, stid):
            return None

        async def list_active(self):
            return []

        async def list_all(self):
            return []

        async def soft_delete(self, stid):
            pass

    class _StubSessionEnrollmentRepo:
        async def active_for_student(self, student_id):
            return []

    class _StubEventSink:
        async def record_session_type_changed(self, **kwargs):
            pass

    class _StubStripe:
        async def update_subscription_proration(self, *a, **kw):
            return None

    _billing_enrollment_repo = _StubBillingEnrollmentRepo()
    _session_type_repo = _StubSessionTypeRepo()
    _session_enrollment_repo = _StubSessionEnrollmentRepo()
    _list_billing_enrollments = ListStudentBillingEnrollments(enrollments=_billing_enrollment_repo)
    _list_session_types = ListSessionTypes(session_types=_session_type_repo)
    _preview_student_session_type_move = PreviewStudentSessionTypeMove(
        enrollments=_billing_enrollment_repo,
        session_types=_session_type_repo,
    )
    _move_student_session_type = MoveStudentSessionType(
        enrollments=_billing_enrollment_repo,
        session_types=_session_type_repo,
        stripe=_StubStripe(),
        event_sink=_StubEventSink(),
    )

    _get_roster = GetSessionRoster(enrollments=enrollments, students=students)

    use_cases = CoachUseCases(
        list_today=ListCoachOccurrencesForDate(occurrences=occurrences, sessions=sessions),
        get_roster=_get_roster,
        get_occurrence_roster=GetOccurrenceRoster(
            get_roster=_get_roster,
            absence_notices=absence_notices,
            occurrence_roster=occurrence_roster,
            students=students,
        ),
        mark_attendance=MarkAttendance(
            attendance_repo=_attendance_repo,
            occurrence_lookup=_occurrence_lookup,
            enrollment_lookup=_enrollment_lookup,
            outbox=_outbox,
            idempotency_store=_idempotency_store,
            academy_id=lambda: "test-academy",
            clock=_now,
        ),
        bulk_mark_attendance=BulkMarkAttendance(
            attendance_repo=_attendance_repo,
            occurrence_lookup=_occurrence_lookup,
            enrollment_lookup=_enrollment_lookup,
            outbox=_outbox,
            idempotency_store=_idempotency_store,
            academy_id=lambda: "test-academy",
            clock=_now,
        ),
        correct_attendance=CorrectAttendance(
            attendance_repo=_attendance_repo,
            occurrence_lookup=_occurrence_lookup,
            outbox=_outbox,
            academy_id=lambda: "test-academy",
            clock=_now,
        ),
        list_attendance_for_occurrence=_attendance_repo.list_for_occurrence,
        get_dashboard_metrics=_dashboard,
        create_lesson_plan=CreateLessonPlan(notes=notes, sessions=session_lookup),
        list_lesson_plans=ListLessonPlans(notes=notes, sessions=session_lookup),
        create_progress_note=CreateProgressNote(
            notes=notes,
            sessions=session_lookup,
            enrollments=enrollments,
        ),
        list_progress_notes=ListProgressNotes(notes=notes, sessions=session_lookup),
        assigned_sessions=session_lookup,
        add_student_to_roster=CoachAddStudentToRoster(
            sessions=rw_store,
            enrollments=enrollment_writer,
            students=student_writer,
            assigned_sessions=session_lookup,
            academy_id=lambda: "test-academy",
        ),
        remove_student_from_roster=CoachRemoveStudentFromRoster(
            enrollments=enrollment_writer,
            assigned_sessions=session_lookup,
        ),
        create_feedback=CreateSessionFeedback(
            feedback_repo=_feedback_repo,
            assignment_lookup=session_lookup,
            outbox=_outbox,
        ),
        list_feedback=ListSessionFeedback(feedback_repo=_feedback_repo),
        list_billing_enrollments=_list_billing_enrollments,
        preview_student_session_type_move=_preview_student_session_type_move,
        move_student_session_type=_move_student_session_type,
        list_session_types=_list_session_types,
        get_billing_enrollment=_billing_enrollment_repo.get,
        get_active_session_enrollments_for_student=_session_enrollment_repo.active_for_student,
        list_all_sessions=ListCoachUpcomingOccurrences(
            occurrences=occurrences,
            sessions=sessions,
        ).execute,
        get_profile=_async_none,
        update_profile=_async_none,
        list_messages=_coach_messages_visible.list_messages,
        mark_message_read=_coach_messages_visible.mark_message_read,
    )
    use_cases._messages_repo = _coach_messages_repo  # type: ignore[attr-defined]
    return use_cases


def _make_app(claims: AuthClaims, use_cases: CoachUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")

    async def _override_claims():
        return claims

    def _override_use_cases():
        return use_cases

    app.dependency_overrides[get_auth_claims] = _override_claims
    app.dependency_overrides[get_coach_use_cases] = _override_use_cases
    return app


@pytest.fixture()
def coach_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        client.messages_repo = use_cases._messages_repo  # type: ignore[attr-defined]
        yield client


@pytest.fixture()
def parent_client(seed) -> Iterator[TestClient]:
    """Same routes mounted, but token represents a parent — wrong persona."""
    use_cases = _build_use_cases(seed)
    app = _make_app(_parent_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def admin_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_admin_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def anon_client(seed) -> Iterator[TestClient]:
    """No auth claims; the dependency raises 401."""
    use_cases = _build_use_cases(seed)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    # Do NOT override get_auth_claims; the default raises 401.
    with TestClient(app) as client:
        yield client


# ====================================================================
# Admin BFF fixtures (Wave 3)
# ====================================================================


from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    GenerateMonthlyPaymentsResult,
    MarkPaymentPaid,
    SendDuesReminders,
    UndoPaymentPaid,
)
from backend.v2.contexts.billing.application.use_cases.finance import (
    AcademyRevenueQuery,
    DeleteExpense,
    EditExpense,
    Expense,
    Payout,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.tuition_discounts import (
    RemoveTuitionDiscount,
    SetTuitionDiscount,
)
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCreditResult,
    WithdrawalCreditPreviewResult,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    PaymentOperationNotAllowed,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentPage,
    AdminStudentSummary,
    decode_student_cursor,
    encode_student_cursor,
    full_name_key,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelSession,
    CreateSession,
    EditRosterAdd,
    EditSession,
    JoinWaitlist,
    OverrideEnrollmentFee,
    PauseEnrollment,
    RemoveFromWaitlist,
    ResumeEnrollment,
    SkipFromWaitlist,
    TransferEnrollment,
    WithdrawEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
    PauseRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
    AdminUserSummary,
    UpdateAdminUser,
)
from backend.v2.contexts.identity.application.use_cases.manage_user_roles import (
    AddUserRole,
    RemoveUserRole,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverSignatureDetail,
    AdminWaiverSummary,
    AdminWaiverTemplateDetail,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.comms import CommsService, Message

# --- in-memory port fakes ---


@dataclass
class _AdminFakeOutbox:
    events: list[Any] = field(default_factory=list)

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, _):
        pass


@dataclass
class _AdminFakeIdempotencyStore:
    data: dict[str, Any] = field(default_factory=dict)

    async def get(self, key):
        return self.data.get(key)

    async def put(self, key, value):
        self.data[key] = value


@dataclass
class FakeSessionWriter:
    """Implements SessionWriter + minimal SessionQuery for the admin reads."""

    sessions: dict[str, Session] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)

    async def try_reserve_seat(self, session_id):
        s = self.sessions.get(session_id)
        if s is None or s.status != "scheduled":
            return False
        if self.reserved.get(session_id, 0) >= s.capacity:
            return False
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id):
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)

    async def update_status(self, session_id, status):
        s = self.sessions[session_id]
        self.sessions[session_id] = s.model_copy(update={"status": status})

    async def get(self, session_id):
        return self.sessions.get(session_id)

    async def create(self, session):
        self.sessions[session.session_id] = session

    async def update(self, session):
        self.sessions[session.session_id] = session

    async def find_duplicate_recurring_series(
        self,
        *,
        title,
        location,
        coach_id,
        days_of_week,
        start_time,
        end_time,
        timezone,
        exclude_session_id=None,
    ):
        def norm(value):
            return " ".join(str(value or "").strip().casefold().split())

        target = (
            norm(location),
            coach_id,
            tuple(days_of_week or []),
            start_time,
            end_time,
            timezone or "America/Chicago",
        )
        for session in self.sessions.values():
            if exclude_session_id and session.session_id == exclude_session_id:
                continue
            if session.status not in {"scheduled", "active", "open"}:
                continue
            candidate = (
                norm(session.location),
                session.coach_id,
                tuple(session.days_of_week or []),
                session.start_time,
                session.end_time,
                session.timezone or "America/Chicago",
            )
            if candidate == target:
                return session
        return None


@dataclass
class FakeAdminOccurrenceRepo:
    rows: dict[str, SessionOccurrence] = field(default_factory=dict)

    async def list_for_session(self, session_id: str) -> list[SessionOccurrence]:
        return [
            occurrence
            for occurrence in sorted(self.rows.values(), key=lambda row: row.start_at)
            if occurrence.session_id == session_id or occurrence.template_session_id == session_id
        ]

    async def get(self, occurrence_id: str) -> SessionOccurrence | None:
        return self.rows.get(occurrence_id)

    async def update_coach_assignment(
        self,
        *,
        occurrence_id: str,
        actual_coach_id: str | None = None,
        substitute_coach_id: str | None = None,
        assignment_reason: str | None = None,
    ) -> SessionOccurrence | None:
        _ = assignment_reason
        occurrence = self.rows.get(occurrence_id)
        if occurrence is None:
            return None
        update: dict[str, str] = {}
        if actual_coach_id is not None:
            update["actual_coach_id"] = actual_coach_id
        if substitute_coach_id is not None:
            update["substitute_coach_id"] = substitute_coach_id
        self.rows[occurrence_id] = occurrence.model_copy(update=update)
        return self.rows[occurrence_id]


@dataclass
class FakeAdminCoachAttendanceRepo:
    rows: dict[tuple[str, str], CoachAttendance] = field(default_factory=dict)

    async def upsert(self, row: CoachAttendance) -> CoachAttendance:
        self.rows[(row.occurrence_id, row.coach_id)] = row
        return row

    async def find_for_occurrence_coach(
        self, occurrence_id: str, coach_id: str
    ) -> CoachAttendance | None:
        return self.rows.get((occurrence_id, coach_id))

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[CoachAttendance]:
        return [row for row in self.rows.values() if row.occurrence_id in occurrence_ids]


@dataclass
class FakeEnrollmentWriter:
    rows: dict[str, Any] = field(default_factory=dict)
    amounts: dict[str, int | None] = field(default_factory=dict)
    move_history: list[dict[str, str]] = field(default_factory=list)

    async def create(self, enrollment):
        self.rows[enrollment.enrollment_id] = enrollment

    async def update_status(self, enrollment_id, status):
        e = self.rows.get(enrollment_id)
        if e is not None:
            self.rows[enrollment_id] = e.model_copy(update={"status": status})

    async def update_session(self, enrollment_id, session_id):
        e = self.rows.get(enrollment_id)
        if e is not None:
            self.move_history.append(
                {
                    "enrollment_id": enrollment_id,
                    "from_session_id": e.session_id,
                    "to_session_id": session_id,
                }
            )
            self.rows[enrollment_id] = e.model_copy(update={"session_id": session_id})

    async def update_amount_cents(self, enrollment_id, amount_cents):
        if enrollment_id in self.rows:
            self.amounts[enrollment_id] = amount_cents

    async def get(self, enrollment_id):
        return self.rows.get(enrollment_id)

    async def active_for_session(self, session_id):
        return [
            enrollment
            for enrollment in self.rows.values()
            if enrollment.session_id == session_id and enrollment.status == "active"
        ]

    async def count_active_for_session(self, session_id):
        return len(await self.active_for_session(session_id))

    async def is_active(self, session_id, student_id):
        return any(
            enrollment.session_id == session_id
            and enrollment.student_id == student_id
            and enrollment.status == "active"
            for enrollment in self.rows.values()
        )

    async def find_for_session_student(self, session_id, student_id):
        return next(
            (
                enrollment
                for enrollment in self.rows.values()
                if enrollment.session_id == session_id and enrollment.student_id == student_id
            ),
            None,
        )


@dataclass
class FakeEnrollmentEvents:
    rows: list[EnrollmentLifecycleEvent] = field(default_factory=list)

    async def record(self, event):
        self.rows.append(event)

    async def list_for_enrollment(self, enrollment_id):
        return [event for event in self.rows if event.enrollment_id == enrollment_id]


@dataclass
class _AdminFakeEnrollmentQuery:
    rows: dict[str, Any] = field(default_factory=dict)

    async def active_for_session(self, session_id):
        return [
            e for e in self.rows.values() if e.session_id == session_id and e.status == "active"
        ]

    async def is_active(self, session_id, student_id):
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self.rows.values()
        )


@dataclass
class FakeEnrollmentAutopayStatus:
    """Fake per-enrollment autopay-status gateway (Slice B).

    Keyed by enrollment_id — mirrors the guarded student_billing_enrollments
    store. Tracks `set_enrollment_status` calls so interface tests can assert
    the admin pause/resume routes toggle the enrollment's autopay status
    (per-enrollment, no Stripe involved). Returns True when applied; returns
    False for an unknown enrollment so caller warning paths are exercised.
    """

    statuses: dict[str, str] = field(default_factory=dict)
    calls: list[dict[str, str]] = field(default_factory=list)
    known_enrollment_ids: set[str] | None = None

    async def set_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
        if self.known_enrollment_ids is not None and enrollment_id not in self.known_enrollment_ids:
            self.calls.append(
                {"enrollment_id": enrollment_id, "status": status, "applied": "false"}
            )
            return False
        self.statuses[enrollment_id] = status
        self.calls.append({"enrollment_id": enrollment_id, "status": status, "applied": "true"})
        return True


@dataclass
class FakeStudentWriter:
    students: dict[str, Any] = field(default_factory=dict)
    admin_status: dict[str, str] = field(default_factory=dict)
    admin_levels: dict[str, str | None] = field(default_factory=dict)

    async def upsert(self, student):
        self.students[student.student_id] = student

    async def ensure_exists(self, student) -> bool:
        """Insert-only, mirroring MongoStudentWriter.ensure_exists."""
        if student.student_id in self.students:
            return False
        self.students[student.student_id] = student
        return True

    async def by_ids(self, student_ids):
        return [
            self.students[student_id] for student_id in student_ids if student_id in self.students
        ]


@dataclass
class FakeWaitlistRepo:
    entries: dict[str, WaitlistEntry] = field(default_factory=dict)

    async def add(self, entry):
        self.entries[entry.waitlist_id] = entry

    async def next_waiting(self, session_id):
        waiting = sorted(
            (
                e
                for e in self.entries.values()
                if e.session_id == session_id and e.status == "waiting"
            ),
            key=lambda e: e.joined_at,
        )
        return waiting[0] if waiting else None

    async def update_status(self, waitlist_id, status):
        e = self.entries.get(waitlist_id)
        if e is not None:
            self.entries[waitlist_id] = e.model_copy(update={"status": status})

    async def find_waiting_for_session_student(self, session_id, student_id):
        return next(
            (
                entry
                for entry in self.entries.values()
                if entry.session_id == session_id
                and entry.student_id == student_id
                and entry.status == "waiting"
            ),
            None,
        )

    async def remove_waiting_for_session_student(self, session_id, student_id):
        self.entries = {
            waitlist_id: entry.model_copy(update={"status": "removed"})
            if entry.session_id == session_id
            and entry.student_id == student_id
            and entry.status == "waiting"
            else entry
            for waitlist_id, entry in self.entries.items()
        }


class FakeLifecycleBilling:
    async def record_move_proration(
        self,
        *,
        enrollment,
        from_session_id,
        to_session_id,
        effective_at,
        actor_id,
        reason,
    ):
        _ = (enrollment, from_session_id, to_session_id, effective_at, actor_id, reason)
        return {
            "billing_policy": "move_proration",
            "billing_result": "recorded",
            "metadata": {},
        }

    async def record_withdrawal_decision(
        self,
        *,
        enrollment,
        outcome,
        effective_at,
        actor_id,
        reason,
    ):
        _ = (enrollment, effective_at, actor_id, reason)
        return {
            "billing_policy": f"withdrawal_{outcome}",
            "billing_result": "recorded",
            "metadata": {"outcome": outcome},
        }


@dataclass
class FakePauseRequestRepo:
    rows: dict[str, PauseRequest] = field(default_factory=dict)

    async def add(self, request):
        self.rows[request.pause_request_id] = request

    async def get(self, pause_request_id):
        return self.rows.get(pause_request_id)

    async def list_for_parent(self, parent_id):
        return [r for r in self.rows.values() if r.parent_id == parent_id]

    async def list_pending(self):
        return [r for r in self.rows.values() if r.status == "pending"]

    async def approve(self, pause_request_id, *, admin_id):
        row = self.rows[pause_request_id].model_copy(
            update={"status": "approved", "decided_by": admin_id}
        )
        self.rows[pause_request_id] = row
        return row

    async def decline(self, pause_request_id, *, admin_id):
        row = self.rows[pause_request_id].model_copy(
            update={"status": "declined", "decided_by": admin_id}
        )
        self.rows[pause_request_id] = row
        return row

    async def enrollment_belongs_to_parent(self, _enrollment_id, _parent_id):
        return True


@dataclass
class FakeBillingDeferrals:
    warnings: list[dict[str, object]] = field(default_factory=list)

    async def list_admin_warnings(self, *, today, limit=100):
        return self.warnings[:limit]

    async def add(self, _deferral) -> None:
        return None

    async def close_active_for_enrollment(
        self,
        _enrollment_id,
        *,
        closed_at,
        closed_by,
        reason,
    ) -> None:
        return None


@dataclass
class FakePaymentRepo:
    rows: dict[str, Payment] = field(default_factory=dict)
    discounts: dict[str, int] = field(default_factory=dict)
    discount_reasons: dict[str, str] = field(default_factory=dict)
    generated_periods: list[str] = field(default_factory=list)
    manual_records: dict[str, dict[str, object]] = field(default_factory=dict)
    credits: list[dict[str, object]] = field(default_factory=list)
    monthly_result: dict[str, object] | None = None

    async def save(self, p):
        self.rows[p.payment_id] = p

    async def get(self, payment_id):
        return self.rows.get(payment_id)

    async def get_by_stripe_pi(self, _):
        return None

    async def get_by_checkout_session(self, _):
        return None

    async def list_for_parent(self, parent_id):
        return [p for p in self.rows.values() if p.parent_id == parent_id]

    async def list_all(self):
        return list(self.rows.values())

    async def generate_monthly_payments(self, period):
        self.generated_periods.append(period)
        if self.monthly_result is not None:
            return GenerateMonthlyPaymentsResult(**self.monthly_result)
        return GenerateMonthlyPaymentsResult(created=1, skipped_existing=0)

    async def mark_payment_paid(
        self,
        payment_id,
        *,
        payment_method,
        notes,
        amount_received_cents=None,
        reference_number=None,
        recorded_by=None,
        payment_date=None,
    ):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.status not in ("pending", "failed", "partially_paid"):
            raise PaymentOperationNotAllowed("only open payments can receive manual payments")
        existing = self.manual_records.get(payment_id, {})
        previous_received = int(existing.get("amount_received_cents", 0))
        amount_due = p.amount_cents
        if amount_received_cents is None:
            amount_received_cents = max(amount_due - previous_received, 0)
        new_received = previous_received + amount_received_cents
        paid_amount = min(new_received, amount_due)
        balance_due = max(amount_due - paid_amount, 0)
        overpayment = max(new_received - amount_due, 0)
        status = "succeeded" if balance_due == 0 else "partially_paid"
        self.manual_records[payment_id] = {
            "payment_method": payment_method,
            "notes": notes,
            "reference_number": reference_number,
            "amount_received_cents": new_received,
            "paid_amount_cents": paid_amount,
            "balance_due_cents": balance_due,
            "overpayment_credit_cents": overpayment,
            "recorded_by": recorded_by,
            "payment_date": payment_date,
        }
        if overpayment and not any(c["payment_id"] == payment_id for c in self.credits):
            self.credits.append(
                {
                    "payment_id": payment_id,
                    "parent_id": p.parent_id,
                    "amount_cents": overpayment,
                }
            )
        self.rows[payment_id] = p.model_copy(update={"status": status})

    async def apply_payment_discount(self, payment_id, discount_cents, *, reason):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.status != "pending":
            raise PaymentOperationNotAllowed("only pending payments can be discounted")
        if discount_cents > p.amount_cents:
            raise PaymentOperationNotAllowed("discount cannot exceed payment amount")
        self.discounts[payment_id] = discount_cents
        self.discount_reasons[payment_id] = reason

    async def undo_payment_paid(self, payment_id):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.stripe_payment_intent_id:
            raise PaymentOperationNotAllowed("Stripe-linked payments must be refunded")
        if p.status != "succeeded":
            raise PaymentOperationNotAllowed("only paid payments can be undone")
        self.rows[payment_id] = p.model_copy(update={"status": "pending"})


@dataclass
class FakeTuitionDiscountRepo:
    active: dict[str, TuitionDiscount] = field(default_factory=dict)
    set_calls: list[dict[str, Any]] = field(default_factory=list)
    remove_calls: list[dict[str, str]] = field(default_factory=list)

    async def set_active(
        self,
        policy: TuitionDiscount,
        *,
        set_by: str,
    ) -> TuitionDiscount:
        saved = policy.model_copy(
            update={
                "academy_id": "acad",
                "set_by": set_by,
                "set_at": _now(),
            }
        )
        self.active[saved.enrollment_id] = saved
        self.set_calls.append({"policy": saved, "set_by": set_by})
        return saved

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None:
        self.active.pop(enrollment_id, None)
        self.remove_calls.append({"enrollment_id": enrollment_id, "ended_by": ended_by})

    async def active_by_enrollments(
        self,
        enrollment_ids: list[str],
    ) -> dict[str, TuitionDiscount]:
        requested = set(enrollment_ids)
        return {
            enrollment_id: policy
            for enrollment_id, policy in self.active.items()
            if enrollment_id in requested
        }


class _FakePreviewWithdrawalCredit:
    async def execute(self, cmd):
        _ = cmd
        return WithdrawalCreditPreviewResult(
            credit_amount_cents=3750,
            paid_tuition_cents=10_000,
            refunded_tuition_cents=0,
            net_paid_tuition_cents=10_000,
            unused_eligible_classes=3,
            paid_period_eligible_classes=8,
            formula="max(10000 - 0, 0) * 3 / 8",
        )


class _FakeApproveWithdrawalCredit:
    async def execute(self, cmd):
        _ = cmd
        return ApproveWithdrawalCreditResult(
            status="APPROVED",
            credit_amount_cents=3750,
            credit_balance_cents=3750,
            credit_id="credit-1",
        )


@dataclass
class FakeExpenseRepo:
    rows: dict[str, Expense] = field(default_factory=dict)

    async def add(self, e):
        self.rows[e.expense_id] = e

    async def list_recent(self, limit: int = 200):
        return sorted(
            (e for e in self.rows.values() if e.deleted_at is None),
            key=lambda e: e.incurred_on,
            reverse=True,
        )[:limit]

    async def get(self, expense_id):
        row = self.rows.get(expense_id)
        return row if row and row.deleted_at is None else None

    async def update(self, expense):
        self.rows[expense.expense_id] = expense

    async def soft_delete(self, expense_id, *, actor_id, reason):
        row = self.rows[expense_id]
        self.rows[expense_id] = row.model_copy(
            update={
                "deleted_at": _now(),
                "deleted_by": actor_id,
                "delete_reason": reason,
            }
        )


@dataclass
class FakePayoutRepo:
    rows: dict[str, Payout] = field(default_factory=dict)

    async def list_all(self):
        return sorted(self.rows.values(), key=lambda p: p.period_start, reverse=True)

    async def list_for_coach(self, coach_id):
        return [p for p in self.rows.values() if p.coach_id == coach_id]


@dataclass
class FakeMessageRepo:
    rows: dict[str, Message] = field(default_factory=dict)

    async def insert(self, m):
        self.rows[m.message_id] = m

    def _visible(self, m, recipient_id, visible_session_ids) -> bool:
        """Mirrors MongoMessageRepository._visibility_filter (#614)."""
        if m.deleted_at is not None:
            return False
        if m.recipient_id == recipient_id:
            return True
        if m.kind != "announcement":
            return False
        if m.scope_type != "session":
            return True
        return m.scope_id in set(visible_session_ids)

    async def for_recipient(self, recipient_id, *, visible_session_ids):
        return sorted(
            (m for m in self.rows.values() if self._visible(m, recipient_id, visible_session_ids)),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def for_admin(self, user_id):
        return sorted(
            (
                m
                for m in self.rows.values()
                if m.deleted_at is None and (m.recipient_id == user_id or m.kind == "announcement")
            ),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def for_session(self, session_id):
        return sorted(
            (
                m
                for m in self.rows.values()
                if m.kind == "announcement"
                and m.scope_type == "session"
                and m.scope_id == session_id
                and m.deleted_at is None
            ),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def get(self, message_id):
        m = self.rows.get(message_id)
        return m if m is not None and m.deleted_at is None else None

    async def soft_delete(self, message_id, deleted_by):
        m = self.rows.get(message_id)
        if m is not None:
            self.rows[message_id] = m.model_copy(
                update={"deleted_at": datetime.now(UTC), "deleted_by": deleted_by}
            )

    async def list_announcements(self):
        return [m for m in self.rows.values() if m.kind == "announcement" and m.deleted_at is None]

    async def mark_read(self, message_id, user_id, *, visible_session_ids):
        # Mirrors MongoMessageRepository.mark_read: only messages the caller
        # can actually read are markable.
        m = self.rows.get(message_id)
        if m is None or not self._visible(m, user_id, visible_session_ids):
            return
        if user_id not in m.read_by:
            m.read_by.append(user_id)


@dataclass
class FakeAdminWaivers:
    report: AdminWaiverReport = field(
        default_factory=lambda: AdminWaiverReport(
            summary=AdminWaiverSummary(
                total_students=0,
                signed_count=0,
                current_count=0,
                pending_count=0,
                outdated_count=0,
            ),
            active_waiver=None,
            rows=[],
        )
    )

    async def execute(self) -> AdminWaiverReport:
        return self.report

    async def template_detail(self, waiver_id: str) -> AdminWaiverTemplateDetail | None:
        if self.report.active_waiver and self.report.active_waiver.waiver_id == waiver_id:
            return AdminWaiverTemplateDetail(
                waiver_id=self.report.active_waiver.waiver_id,
                title=self.report.active_waiver.title
                or f"Waiver {self.report.active_waiver.version}",
                version=self.report.active_waiver.version,
                body=self.report.active_waiver.body,
                content_hash=self.report.active_waiver.content_hash,
                effective_from=self.report.active_waiver.effective_from,
            )
        return None

    async def signature_detail(self, signature_id: str) -> AdminWaiverSignatureDetail | None:
        for row in self.report.rows:
            if row.signature_id == signature_id and row.signed_at is not None:
                return AdminWaiverSignatureDetail(
                    signature_id=signature_id,
                    student_id=row.student_id,
                    student_name=row.student_name,
                    parent_id=row.parent_id,
                    parent_name=row.parent_name,
                    parent_email=row.parent_email,
                    signed_at=row.signed_at,
                    waiver_template_id=row.waiver_template_id,
                    waiver_title="Annual waiver",
                    waiver_version=row.waiver_version,
                    content_hash=row.content_hash,
                    artifact_status=row.artifact_status,
                    share_status=row.share_status,
                )
        return None


# --- seed data ---


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.fixture
def admin_seed():
    sessions = FakeSessionWriter()
    enrollments = FakeEnrollmentWriter()
    occurrences = FakeAdminOccurrenceRepo()
    coach_attendance = FakeAdminCoachAttendanceRepo()
    sessions.sessions["sess-1"] = Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        capacity=8,
        status="scheduled",
    )
    occurrences.rows["occ-admin-1"] = SessionOccurrence(
        occurrence_id="occ-admin-1",
        academy_id="acad",
        session_id="sess-1",
        start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        status="scheduled",
        scheduled_coach_id="coach-1",
    )
    return {
        "sessions": sessions,
        "occurrences": occurrences,
        "coach_attendance": coach_attendance,
        "enrollments": enrollments,
        "enrollment_query": enrollments,
        "enrollment_events": FakeEnrollmentEvents(),
        "students": FakeStudentWriter(),
        "waitlist": FakeWaitlistRepo(),
        "pause_requests": FakePauseRequestRepo(),
        "billing_deferrals": FakeBillingDeferrals(),
        "autopay_status": FakeEnrollmentAutopayStatus(),
        "payments": FakePaymentRepo(),
        "tuition_discounts": FakeTuitionDiscountRepo(),
        "expenses": FakeExpenseRepo(),
        "payouts": FakePayoutRepo(),
        "messages": FakeMessageRepo(),
        "waivers": FakeAdminWaivers(),
        "invoice_details": {},
        "invoice_artifacts": {},
        "outbox": _AdminFakeOutbox(),
        "idempotency": _AdminFakeIdempotencyStore(),
        "stripe": FakeStripeGateway(),
    }


class _FakeLoginInviteSender:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.known = {"coach-1", "u-admin", "p-1"}

    async def execute(self, user_id, *, academy_id):
        from datetime import UTC, datetime

        from backend.v2.contexts.identity.application.errors import UserNotFound
        from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
            LoginInviteResult,
        )

        if user_id not in self.known:
            raise UserNotFound(user_id)
        self.sent.append(user_id)
        return LoginInviteResult(sent_at=datetime.now(UTC))


def _build_admin_use_cases(seed) -> AdminUseCases:
    sessions = seed["sessions"]
    occurrences = seed["occurrences"]
    coach_attendance = seed["coach_attendance"]
    enrollments_w = seed["enrollments"]
    enrollments_q = seed["enrollment_query"]
    enrollment_events = seed["enrollment_events"]
    students = seed["students"]
    waitlist = seed["waitlist"]
    pause_requests = seed["pause_requests"]
    billing_deferrals = seed["billing_deferrals"]
    autopay_status = seed["autopay_status"]
    lifecycle_billing = FakeLifecycleBilling()
    payments = seed["payments"]
    tuition_discounts = seed["tuition_discounts"]
    outbox = seed["outbox"]
    idem = seed["idempotency"]
    stripe = seed["stripe"]
    expenses = seed["expenses"]
    payouts = seed["payouts"]
    messages = seed["messages"]
    waivers = seed["waivers"]
    comms = CommsService(messages=messages, academy_id="acad")  # type: ignore[arg-type]

    create_session = CreateSession(sessions=sessions, academy_id="acad")
    edit_session = EditSession(sessions=sessions)
    cancel_session = CancelSession(
        sessions=sessions,
        enrollments_query=enrollments_q,
        enrollments_writer=enrollments_w,
        outbox=outbox,
        academy_id="acad",
    )
    edit_roster_add = EditRosterAdd(
        sessions=sessions,
        enrollments=enrollments_w,
        students=students,
        enrollment_events=enrollment_events,
        academy_id="acad",
    )
    cancel_enrollment = CancelEnrollment(
        enrollments=enrollments_w,
        sessions=sessions,
        outbox=outbox,
        enrollment_events=enrollment_events,
        academy_id="acad",
    )
    transfer_enrollment = TransferEnrollment(
        enrollments=enrollments_w,
        sessions=sessions,
        enrollment_events=enrollment_events,
        billing=lifecycle_billing,
    )
    override_enrollment_fee = OverrideEnrollmentFee(enrollments=enrollments_w)
    pause_enrollment = PauseEnrollment(
        enrollments=enrollments_w,
        sessions=sessions,
        students=students,
        waitlist=waitlist,
        enrollment_events=enrollment_events,
        autopay_status=autopay_status,
    )
    resume_enrollment = ResumeEnrollment(
        enrollments=enrollments_w,
        sessions=sessions,
        students=students,
        waitlist=waitlist,
        enrollment_events=enrollment_events,
        autopay_status=autopay_status,
    )
    withdraw_enrollment = WithdrawEnrollment(
        enrollments=enrollments_w,
        enrollment_events=enrollment_events,
        billing=lifecycle_billing,
    )
    join_waitlist = JoinWaitlist(
        waitlist=waitlist,
        enrollment_events=enrollment_events,
        academy_id="acad",
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions,
        enrollments=enrollments_w,
        outbox=outbox,
        enrollment_events=enrollment_events,
        academy_id=lambda: "acad",
    )
    skip = SkipFromWaitlist(waitlist=waitlist)
    remove = RemoveFromWaitlist(waitlist=waitlist)
    list_admin_pause_requests = ListAdminPauseRequests(pause_requests=pause_requests)
    approve_pause_request = ApprovePauseRequest(
        pause_requests=pause_requests,
        pause_enrollment=pause_enrollment,
        billing_deferrals=billing_deferrals,
        autopay_status=autopay_status,
    )
    decline_pause_request = DeclinePauseRequest(pause_requests=pause_requests)
    issue_refund = IssueRefund(
        payment_repo=payments, stripe=stripe, outbox=outbox, idempotency_store=idem
    )
    generate_monthly_payments = GenerateMonthlyPayments(payments=payments)
    mark_payment_paid = MarkPaymentPaid(payments=payments)
    apply_payment_discount = ApplyPaymentDiscount(payments=payments)
    undo_payment_paid = UndoPaymentPaid(payments=payments)
    set_tuition_discount = SetTuitionDiscount(discounts=tuition_discounts)
    remove_tuition_discount = RemoveTuitionDiscount(discounts=tuition_discounts)
    record_expense = RecordExpense(expenses=expenses, academy_id="acad")  # type: ignore[arg-type]
    edit_expense = EditExpense(expenses=expenses)  # type: ignore[arg-type]
    delete_expense = DeleteExpense(expenses=expenses)  # type: ignore[arg-type]
    revenue_query = AcademyRevenueQuery(payments=payments)

    async def list_admin_sessions(on_date, *, window=None, coach_id=None):
        # Mirrors production: cancel is a soft delete, so cancelled sessions
        # must never come back from the admin listings.
        live = [
            s
            for s in sessions.sessions.values()
            if str(getattr(s, "status", None) or "scheduled") != "cancelled"
        ]
        if window == "upcoming":
            today = _now().date()
            return [s for s in live if s.start_at.date() >= today]
        if on_date is None:
            on_date = _now().date()
        return [s for s in live if s.start_at.date() == on_date]

    async def list_admin_enrollments_for_session(session_id):
        active = await enrollments_q.active_for_session(session_id)
        out = []
        for e in active:
            st = students.students.get(e.student_id)
            out.append(
                {
                    "enrollment_id": e.enrollment_id,
                    "session_id": e.session_id,
                    "student_id": e.student_id,
                    "student_name": st.full_name if st else "(unknown)",
                    "full_name": st.full_name if st else "(unknown)",
                    "parent_id": st.parent_id if st else "",
                    "status": e.status,
                    "level": students.admin_levels.get(e.student_id),
                    "dues_status": students.admin_status.get(e.student_id, "current"),
                }
            )
        return out

    async def _occurrence_row(occurrence):
        return {
            "occurrence_id": occurrence.occurrence_id,
            "session_id": occurrence.template_session_id or occurrence.session_id,
            "start_at": occurrence.start_at,
            "end_at": occurrence.end_at,
            "status": occurrence.status,
            "scheduled_coach_id": occurrence.scheduled_coach_id,
            "actual_coach_id": occurrence.actual_coach_id,
            "substitute_coach_id": occurrence.substitute_coach_id,
            "attendance_marked_count": 0,
            "attendance_marked_by": [],
            "attendance_last_marked_at": None,
            "coach_attendance": [
                row.model_dump(exclude={"academy_id"})
                for row in await coach_attendance.list_for_occurrences([occurrence.occurrence_id])
            ],
        }

    async def list_session_occurrences(session_id):
        rows = await occurrences.list_for_session(session_id)
        return [await _occurrence_row(row) for row in rows]

    async def update_session_occurrence_coach(
        *,
        occurrence_id,
        actual_coach_id,
        substitute_coach_id,
        actor_id,
        reason,
    ):
        _ = (actor_id, reason)
        row = await occurrences.update_coach_assignment(
            occurrence_id=occurrence_id,
            actual_coach_id=actual_coach_id,
            substitute_coach_id=substitute_coach_id,
        )
        return None if row is None else await _occurrence_row(row)

    class _AdminOccurrenceLookup:
        async def get(self, occurrence_id: str):
            occurrence = await occurrences.get(occurrence_id)
            if occurrence is None:
                return None
            return OccurrenceDetails(
                occurrence_id=occurrence.occurrence_id,
                session_id=occurrence.session_id,
                starts_at=occurrence.start_at,
                status=occurrence.status,
                scheduled_coach_id=occurrence.scheduled_coach_id,
                actual_coach_id=occurrence.actual_coach_id,
                substitute_coach_id=occurrence.substitute_coach_id,
                template_session_id=occurrence.template_session_id,
            )

    mark_coach_attendance = MarkCoachAttendance(
        coach_attendance=coach_attendance,
        occurrence_lookup=_AdminOccurrenceLookup(),
        academy_id="acad",
        clock=lambda: datetime(2026, 5, 16, 10, 35, tzinfo=UTC),
    )

    _student_attendance = FakeAttendanceRepo()
    _student_attendance.saved.append(
        Attendance(
            attendance_id="att-admin-1",
            academy_id="acad",
            occurrence_id="occ-admin-1",
            session_id="sess-1",
            student_id="st-1",
            marked_by="coach-1",
            marked_at=datetime(2026, 5, 16, 9, 5, tzinfo=UTC),
            status="present",
        )
    )
    correct_attendance = CorrectAttendance(
        attendance_repo=_student_attendance,
        occurrence_lookup=_AdminOccurrenceLookup(),
        outbox=outbox,
        academy_id=lambda: "acad",
        clock=lambda: datetime(2026, 6, 20, 10, 35, tzinfo=UTC),
    )

    async def list_waitlist_for_session(session_id):
        return [e for e in waitlist.entries.values() if e.session_id == session_id]

    async def list_payments_recent():
        return list(payments.rows.values())

    async def quote_enrollment(*, session_id, student_id=None, start_date=None):
        _ = (session_id, student_id, start_date)
        return BillingCalculationSnapshot(
            snapshot_id="snap-1",
            monthly_price_cents=10_000,
            billing_period_start=datetime(2026, 5, 1, tzinfo=UTC),
            billing_period_end=datetime(2026, 6, 1, tzinfo=UTC),
            billing_period_label="2026-05",
            timezone="America/Chicago",
            total_eligible_classes=8,
            billable_remaining_classes=3,
            proration_ratio="3/8",
            final_amount_cents=3_750,
            included_occurrence_ids=["class-6", "class-7", "class-8"],
            excluded_occurrences={"class-1": "ELAPSED_BEFORE_ENROLLMENT"},
            calculated_at=datetime(2026, 5, 16, tzinfo=UTC),
            calculated_by="admin",
        )

    async def list_audit_logs():
        return []

    async def list_dues_followup():
        return []

    async def get_billing_invoice_detail(invoice_id):
        return seed["invoice_details"][invoice_id]

    async def generate_billing_invoice_artifact(invoice_id, artifact_type):
        artifact_id = f"{artifact_type}-{invoice_id}"
        seed["invoice_artifacts"][artifact_id] = {
            "invoice_id": invoice_id,
            "artifact_type": artifact_type,
        }
        return {"artifact_id": artifact_id, "artifact_type": artifact_type, "status": "generated"}

    class _FakeDuesReminderSender:
        async def send_dues_reminders(self, *, parent_ids, generate_invoice_artifacts):
            generated = len(parent_ids or []) if generate_invoice_artifacts else 0
            return {
                "sent": len(parent_ids or []),
                "blocked": False,
                "reason": None,
                "selected_parent_ids": parent_ids or [],
                "generated_invoice_artifacts": generated,
            }

    send_dues_reminders = SendDuesReminders(sender=_FakeDuesReminderSender())

    async def export_report_csv(report_name):
        return f"name\n{report_name}\n"

    class _ListAdminUsers:
        async def execute(self, role=None, academy_id=None):
            _ = academy_id
            users = [
                AdminUserSummary(
                    user_id="coach-1",
                    email="coach@example.com",
                    display_name="Coach One",
                    role="coach",
                    status="active",
                ),
                AdminUserSummary(
                    user_id="p-1",
                    email="parent@example.com",
                    display_name="Parent One",
                    role="parent",
                    status="active",
                ),
                AdminUserSummary(
                    user_id="adm",
                    email="admin@example.com",
                    display_name="Admin One",
                    role="admin",
                    status="active",
                ),
            ]
            return [u for u in users if role is None or u.role == role]

    class _ListAdminStudents:
        async def execute(self, search=None, status=None, limit=50, cursor=None, missing=()):
            from backend.v2.shared.profile.completeness import CHILD_REQUIRED

            unknown = set(missing) - set(CHILD_REQUIRED)
            if unknown:
                raise ValueError(f"Unknown missing field(s): {', '.join(sorted(unknown))}")
            rows = []
            search_key = full_name_key(search or "") if search else None
            for s in students.students.values():
                row_status = students.admin_status.get(s.student_id, "active")
                if status and row_status != status:
                    continue
                parent_name = "Parent One" if s.parent_id == "p-1" else None
                parent_email = "parent@example.com" if s.parent_id == "p-1" else None
                haystack = " ".join(
                    full_name_key(value)
                    for value in (s.full_name, parent_name or "", parent_email or "")
                )
                if search_key and search_key not in haystack:
                    continue
                rows.append(
                    {
                        "summary": AdminStudentSummary(
                            student_id=s.student_id,
                            full_name=s.full_name,
                            parent_id=s.parent_id,
                            parent_name=parent_name,
                            parent_email=parent_email,
                            status=row_status,
                            active_session_count=1,
                            attendance_rate=None,
                            dues_status="current",
                        ),
                        "full_name_key": full_name_key(s.full_name),
                    }
                )
            rows.sort(key=lambda row: (row["full_name_key"], row["summary"].student_id))
            if cursor:
                decoded = decode_student_cursor(cursor)
                rows = [
                    row
                    for row in rows
                    if (row["full_name_key"], row["summary"].student_id)
                    > (decoded.full_name_key, decoded.student_id)
                ]
            page_rows = rows[: limit + 1]
            has_next = len(page_rows) > limit
            page_rows = page_rows[:limit]
            next_cursor = None
            if has_next and page_rows:
                last = page_rows[-1]
                next_cursor = encode_student_cursor(
                    last["full_name_key"],
                    last["summary"].student_id,
                )
            return AdminStudentPage(
                students=[row["summary"] for row in page_rows],
                next_cursor=next_cursor,
            )

    class _FakeRoleModifier:
        def __init__(self) -> None:
            self.roles: dict[str, list[str]] = {
                "coach-1": ["coach"],
                "u-admin": ["admin"],
            }

        def _detail(self, user_id: str) -> AdminUserDetail:
            roles = self.roles[user_id]
            return AdminUserDetail(
                user_id=user_id,
                email=f"{user_id}@example.com",
                display_name=user_id,
                role=roles[0],
                status="active",
                phone=None,
                roles=roles,
                linked_student_count=0,
                session_count=0,
            )

        async def add_role(self, user_id, role, *, academy_id, actor_id, reason):
            if user_id not in self.roles:
                return None
            if role not in self.roles[user_id]:
                self.roles[user_id].append(role)
            return self._detail(user_id)

        async def remove_role(self, user_id, role, *, academy_id, actor_id, reason):
            from backend.v2.contexts.identity.application.errors import (
                CannotRemoveLastRole,
            )

            if user_id not in self.roles:
                return None
            remaining = [r for r in self.roles[user_id] if r != role]
            if not remaining:
                raise CannotRemoveLastRole(user_id)
            self.roles[user_id] = remaining
            return self._detail(user_id)

    _role_modifier = _FakeRoleModifier()
    _login_invite_sender = _FakeLoginInviteSender()

    class _FakeAdminUserEditor:
        """Backs PATCH /admin/users/{id} so the #436 re-invite path is testable.

        `p-2` is deliberately absent from `_FakeLoginInviteSender.known`, so
        editing its email exercises a failing invite send.
        """

        def __init__(self) -> None:
            self.users: dict[str, AdminUserDetail] = {
                "p-1": AdminUserDetail(
                    user_id="p-1",
                    email="parent@example.com",
                    display_name="Parent One",
                    role="parent",
                    status="active",
                    roles=("parent",),
                ),
                "p-2": AdminUserDetail(
                    user_id="p-2",
                    email="parent2@example.com",
                    display_name="Parent Two",
                    role="parent",
                    status="active",
                    roles=("parent",),
                ),
            }

        async def get_admin_user(self, user_id, *, academy_id):
            _ = academy_id
            return self.users.get(user_id)

        async def update_admin_user(self, user_id, command, *, academy_id):
            _ = academy_id
            user = self.users.get(user_id)
            if user is None:
                return None
            update: dict[str, object] = {}
            if command.email is not None:
                update["email"] = str(command.email)
            if command.display_name is not None:
                update["display_name"] = command.display_name
            if command.status is not None:
                update["status"] = command.status
            self.users[user_id] = user.model_copy(update=update)
            return self.users[user_id]

    _admin_user_editor = _FakeAdminUserEditor()

    return AdminUseCases(
        list_admin_users=_ListAdminUsers(),  # type: ignore[arg-type]
        send_login_invite=_login_invite_sender,  # type: ignore[arg-type]
        update_admin_user=UpdateAdminUser(
            _admin_user_editor,  # type: ignore[arg-type]
            reader=_admin_user_editor,  # type: ignore[arg-type]
            invites=_login_invite_sender,
        ),
        list_admin_students=_ListAdminStudents(),  # type: ignore[arg-type]
        create_session=create_session,
        edit_session=edit_session,
        cancel_session=cancel_session,
        edit_roster_add=edit_roster_add,
        cancel_enrollment=cancel_enrollment,
        transfer_enrollment=transfer_enrollment,
        override_enrollment_fee=override_enrollment_fee,
        pause_enrollment=pause_enrollment,
        resume_enrollment=resume_enrollment,
        withdraw_enrollment=withdraw_enrollment,
        join_waitlist=join_waitlist,
        promote_from_waitlist=promote,
        skip_from_waitlist=skip,
        remove_from_waitlist=remove,
        list_admin_pause_requests=list_admin_pause_requests,
        approve_pause_request=approve_pause_request,
        decline_pause_request=decline_pause_request,
        issue_refund=issue_refund,
        quote_enrollment=quote_enrollment,
        preview_withdrawal_credit=_FakePreviewWithdrawalCredit(),  # type: ignore[arg-type]
        approve_withdrawal_credit=_FakeApproveWithdrawalCredit(),  # type: ignore[arg-type]
        list_payments_recent=list_payments_recent,
        list_billing_invoices=AsyncMock(return_value=[]),
        get_billing_invoice_detail=get_billing_invoice_detail,
        generate_billing_invoice_artifact=generate_billing_invoice_artifact,
        generate_monthly_payments=generate_monthly_payments,
        mark_payment_paid=mark_payment_paid,
        apply_payment_discount=apply_payment_discount,
        undo_payment_paid=undo_payment_paid,
        record_expense=record_expense,
        edit_expense=edit_expense,
        delete_expense=delete_expense,
        expenses=expenses,  # type: ignore[arg-type]
        payouts=payouts,  # type: ignore[arg-type]
        revenue_query=revenue_query,
        list_admin_sessions=list_admin_sessions,
        list_session_occurrences=list_session_occurrences,
        update_session_occurrence_coach=update_session_occurrence_coach,
        mark_coach_attendance=mark_coach_attendance,
        correct_attendance=correct_attendance,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        list_audit_logs=list_audit_logs,
        list_dues_followup=list_dues_followup,
        list_billing_deferral_warnings=billing_deferrals.list_admin_warnings,
        send_dues_reminders=send_dues_reminders,
        export_report_csv=export_report_csv,
        get_reports_kpis=AsyncMock(
            return_value={
                "active_students": 0,
                "attendance_rate_30d": 0.0,
                "dues_collected_mtd_cents": 0,
                "pending_waivers": 0,
            }
        ),
        list_enrollment_events=enrollment_events.list_for_enrollment,
        comms=comms,
        list_admin_waivers=waivers,  # type: ignore[arg-type]
        admin_registration_review=AsyncMock(),
        get_academy_use_case=AsyncMock(),
        update_academy_use_case=AsyncMock(),
        get_academy_fees_use_case=AsyncMock(),
        update_academy_fees_use_case=AsyncMock(),
        get_academy_notifications_use_case=AsyncMock(),
        update_academy_notifications_use_case=AsyncMock(),
        get_academy_gateway_use_case=AsyncMock(),
        change_user_role=AsyncMock(),
        add_user_role=AddUserRole(_role_modifier),  # type: ignore[arg-type]
        remove_user_role=RemoveUserRole(_role_modifier),  # type: ignore[arg-type]
        set_tuition_discount=set_tuition_discount,
        remove_tuition_discount=remove_tuition_discount,
        tuition_discounts=tuition_discounts,
        reconcile_stripe_billing=AsyncMock(return_value={}),
        list_billing_setup=AsyncMock(),
        send_add_card_reminder=AsyncMock(),
        charge_billing_setup_balance=AsyncMock(),
        enable_billing_setup_autopay=AsyncMock(),
        record_billing_setup_invite=AsyncMock(),
    )


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _make_admin_app(claims: AuthClaims, use_cases: AdminUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return app


@pytest.fixture
def admin_client(admin_seed) -> Iterator[TestClient]:  # noqa: F811
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("admin"), uc)
    with TestClient(app) as client:
        client.seed = admin_seed  # type: ignore[attr-defined]
        client.use_cases = uc  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def coach_on_admin_client(admin_seed) -> Iterator[TestClient]:
    """Coach token hitting admin routes → must 404."""
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("coach"), uc)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def parent_on_admin_client(admin_seed) -> Iterator[TestClient]:
    """Parent token hitting admin routes → must 404."""
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("parent"), uc)
    with TestClient(app) as client:
        yield client
