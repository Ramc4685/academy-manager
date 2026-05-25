"""Admin registration review application workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
    ApproveRegistrationCommand,
    WaitlistRegistrationCommand,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.onboarding.domain.errors import IncompleteApplication
from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
)

NOW = datetime(2026, 5, 24, tzinfo=UTC)
ACADEMY_ID = "acad-1"


class InMemoryApplications:
    def __init__(self, app: Application) -> None:
        self.apps = {app.application_id: app}
        self.saved: list[Application] = []

    async def save(self, app: Application) -> None:
        self.apps[app.application_id] = app
        self.saved.append(app)

    async def get(self, application_id: str) -> Application | None:
        return self.apps.get(application_id)

    async def latest_for_parent(self, parent_user_id: str) -> Application | None:
        return next(
            (app for app in self.apps.values() if app.parent_user_id == parent_user_id),
            None,
        )

    async def get_by_payment_id(self, payment_id: str) -> Application | None:
        return next(
            (app for app in self.apps.values() if app.payment_id == payment_id),
            None,
        )

    async def list_by_status(self, statuses: list[str]) -> list[Application]:
        return [app for app in self.apps.values() if app.status in statuses]


class InMemorySessions:
    def __init__(self, sessions: list[Session]) -> None:
        self.sessions = {session.session_id: session for session in sessions}
        self.reserve_calls = 0

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserve_calls += 1
        return session_id in self.sessions

    async def release_seat(self, session_id: str) -> None:
        return None

    async def update_status(self, session_id: str, status: str) -> None:
        return None

    async def create(self, session: Session) -> None:
        self.sessions[session.session_id] = session

    async def update(self, session: Session) -> None:
        self.sessions[session.session_id] = session


class InMemoryStudents:
    def __init__(self) -> None:
        self.upserts: list[Student] = []

    async def upsert(self, student: Student) -> None:
        self.upserts.append(student)


class InMemoryEnrollments:
    def __init__(self, existing: list[Enrollment] | None = None) -> None:
        self.created: list[Enrollment] = []
        self.enrollments = {
            (enrollment.session_id, enrollment.student_id): enrollment
            for enrollment in existing or []
        }

    async def create(self, enrollment: Enrollment) -> None:
        self.created.append(enrollment)
        self.enrollments[(enrollment.session_id, enrollment.student_id)] = enrollment

    async def update_status(self, enrollment_id: str, status: str) -> None:
        return None

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        return None

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return next(
            (
                enrollment
                for enrollment in self.enrollments.values()
                if enrollment.enrollment_id == enrollment_id
            ),
            None,
        )

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return self.enrollments.get((session_id, student_id))


class InMemoryWaitlist:
    def __init__(self) -> None:
        self.entries: list[WaitlistEntry] = []

    async def add(self, entry: WaitlistEntry) -> None:
        self.entries.append(entry)

    async def next_waiting(self, session_id: str) -> WaitlistEntry | None:
        return None

    async def update_status(self, waitlist_id: str, status: str) -> None:
        return None

    async def find_waiting_for_session_student(
        self, session_id: str, student_id: str
    ) -> WaitlistEntry | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry.session_id == session_id
                and entry.student_id == student_id
                and entry.status == "waiting"
            ),
            None,
        )

    async def remove_waiting_for_session_student(self, session_id: str, student_id: str) -> None:
        return None


def _application(*, student_id: str | None = "student-1") -> Application:
    return Application(
        application_id="app-1",
        academy_id=ACADEMY_ID,
        parent_user_id="parent-1",
        parent_email="parent@example.com",
        status="PENDING_APPROVAL",
        parent_profile=ParentProfile(first_name="Pat", last_name="Parent"),
        child_profile=ChildProfile(first_name="Sam", last_name="Student"),
        selected_session_id="sess-1",
        student_id=student_id,
        expires_at=NOW + timedelta(days=7),
        created_at=NOW,
        updated_at=NOW,
    )


def _session() -> Session:
    return Session(
        session_id="sess-1",
        academy_id=ACADEMY_ID,
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=NOW + timedelta(days=1),
        end_at=NOW + timedelta(days=1, hours=1),
        capacity=8,
    )


@pytest.mark.asyncio
async def test_approve_reuses_existing_enrollment_without_reserving_seat() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([_session()])
    existing = Enrollment(
        enrollment_id="enroll-existing",
        academy_id=ACADEMY_ID,
        session_id="sess-1",
        student_id="student-1",
        status="active",
    )
    enrollments = InMemoryEnrollments([existing])
    students = InMemoryStudents()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=students,
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    detail = await review.approve(
        ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")
    )

    assert sessions.reserve_calls == 0
    assert enrollments.created == []
    assert detail.enrollment_id == "enroll-existing"
    assert apps.saved[-1].enrollment_id == "enroll-existing"


@pytest.mark.asyncio
async def test_waitlist_requires_existing_session_before_writes() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([])
    students = InMemoryStudents()
    waitlist = InMemoryWaitlist()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=students,
        enrollments=InMemoryEnrollments(),
        waitlist=waitlist,
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    with pytest.raises(IncompleteApplication, match="Selected session is not available"):
        await review.waitlist(
            WaitlistRegistrationCommand(application_id="app-1", actor_id="admin-1")
        )

    assert students.upserts == []
    assert waitlist.entries == []
    assert apps.saved == []
