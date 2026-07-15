"""Admin registration review application workflow tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
    ApproveRegistrationCommand,
    RejectRegistrationCommand,
    WaitlistRegistrationCommand,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationNotEditable,
    IncompleteApplication,
)
from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
    WaiverAcceptance,
    WaiverSignature,
)
from backend.v2.shared.ids import stable_ulid

NOW = datetime(2026, 5, 24, tzinfo=UTC)
ACADEMY_ID = "acad-1"


class InMemoryApplications:
    def __init__(self, app: Application | list[Application]) -> None:
        apps = app if isinstance(app, list) else [app]
        self.apps = {item.application_id: item for item in apps}
        self.saved: list[Application] = []
        self._lock = asyncio.Lock()

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

    async def claim_for_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
        stale_before: datetime,
    ) -> Application | None:
        async with self._lock:
            app = self.apps.get(application_id)
            stale = app is not None and (
                app.review_claimed_at is None or app.review_claimed_at <= stale_before
            )
            if app is None or (
                app.status != "PENDING_APPROVAL"
                and not (app.status in {"APPROVING", "WAITLISTING", "DECLINING"} and stale)
            ):
                return None
            claimed = app.model_copy(
                update={
                    "status": processing_status,
                    "review_claimed_at": updated_at,
                    "review_claim_token": claim_token,
                    "updated_at": updated_at,
                }
            )
            self.apps[application_id] = claimed
            return claimed

    async def release_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
    ) -> None:
        async with self._lock:
            app = self.apps.get(application_id)
            if (
                app is not None
                and app.status == processing_status
                and app.review_claim_token == claim_token
            ):
                self.apps[application_id] = app.model_copy(
                    update={
                        "status": "PENDING_APPROVAL",
                        "review_claimed_at": None,
                        "review_claim_token": None,
                        "updated_at": updated_at,
                    }
                )

    async def renew_review_claim(
        self, application_id: str, claim_token: str, *, claimed_at: datetime
    ) -> bool:
        async with self._lock:
            app = self.apps.get(application_id)
            if app is None or app.review_claim_token != claim_token:
                return False
            self.apps[application_id] = app.model_copy(
                update={"review_claimed_at": claimed_at, "updated_at": claimed_at}
            )
            return True

    async def complete_review(self, app: Application, *, claim_token: str) -> bool:
        async with self._lock:
            current = self.apps.get(app.application_id)
            if current is None or current.review_claim_token != claim_token:
                return False
            completed = app.model_copy(
                update={"review_claimed_at": None, "review_claim_token": None}
            )
            self.apps[app.application_id] = completed
            self.saved.append(completed)
            return True


class InMemorySessions:
    def __init__(self, sessions: list[Session]) -> None:
        self.sessions = {session.session_id: session for session in sessions}
        self.reserve_calls = 0
        self.release_calls = 0

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserve_calls += 1
        return session_id in self.sessions

    async def release_seat(self, session_id: str) -> None:
        self.release_calls += 1

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


class InMemoryWaiverSignatures:
    def __init__(self) -> None:
        self.saved: list[WaiverSignature] = []

    async def save_signature(self, signature: WaiverSignature) -> None:
        self.saved.append(signature)


class InMemoryEnrollments:
    def __init__(self, existing: list[Enrollment] | None = None) -> None:
        self.created: list[Enrollment] = []
        self.enrollments = {
            (enrollment.session_id, enrollment.student_id): enrollment
            for enrollment in existing or []
        }
        self.skip_periods: dict[str, list[str]] = {}

    async def create(self, enrollment: Enrollment) -> None:
        self.created.append(enrollment)
        self.enrollments[(enrollment.session_id, enrollment.student_id)] = enrollment

    async def create_if_absent(self, enrollment: Enrollment) -> bool:
        key = (enrollment.session_id, enrollment.student_id)
        if key in self.enrollments:
            return False
        await self.create(enrollment)
        return True

    async def update_status(self, enrollment_id: str, status: str) -> None:
        return None

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        return None

    async def add_skip_period(self, enrollment_id: str, period: str) -> None:
        self.skip_periods.setdefault(enrollment_id, []).append(period)

    async def set_enrolled_at_if_missing(self, enrollment_id: str, enrolled_at: datetime) -> None:
        for key, enrollment in self.enrollments.items():
            if enrollment.enrollment_id == enrollment_id and enrollment.enrolled_at is None:
                self.enrollments[key] = enrollment.model_copy(update={"enrolled_at": enrolled_at})

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


class ConcurrentEnrollments(InMemoryEnrollments):
    def __init__(self) -> None:
        super().__init__()
        self._find_calls = 0
        self._both_found_missing = asyncio.Event()

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        result = await super().find_for_session_student(session_id, student_id)
        self._find_calls += 1
        if self._find_calls >= 2:
            self._both_found_missing.set()
        await self._both_found_missing.wait()
        return result


class RegistrationTrackingEnrollments(InMemoryEnrollments):
    def __init__(self, registrations: ExistingStudentRegistrations) -> None:
        super().__init__()
        self._registrations = registrations

    async def create(self, enrollment: Enrollment) -> None:
        await super().create(enrollment)
        self._registrations.active = True
        self._registrations.enrollment_id = enrollment.enrollment_id


class ExistingStudentRegistrations:
    def __init__(
        self,
        *,
        student_id: str | None = None,
        active: bool = False,
        ambiguous: bool = False,
        enrollment_id: str = "existing-enrollment",
    ) -> None:
        self.student_id = student_id
        self.active = active
        self.ambiguous = ambiguous
        self.enrollment_id = enrollment_id
        self.claimed_by: str | None = None
        self.claimed_at: datetime | None = None
        self.claim_token: str | None = None

    async def find_registration_student(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> str | None:
        return self.student_id

    async def has_ambiguous_registration_match(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> bool:
        return self.ambiguous

    async def has_active_enrollment(
        self,
        student_id: str,
        *,
        exclude_enrollment_id: str | None = None,
    ) -> bool:
        return (
            self.active
            and student_id == self.student_id
            and self.enrollment_id != exclude_enrollment_id
        )

    async def claim_registration(
        self,
        student_id: str,
        application_id: str,
        *,
        claim_token: str,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        if (
            self.claimed_by is not None
            and not (self.claimed_by == application_id and self.claim_token == claim_token)
            and self.claimed_at is not None
            and self.claimed_at > stale_before
        ):
            return False
        self.claimed_by = application_id
        self.claimed_at = claimed_at
        self.claim_token = claim_token
        return True

    async def release_registration(
        self, student_id: str, application_id: str, *, claim_token: str
    ) -> None:
        if self.claimed_by == application_id and self.claim_token == claim_token:
            self.claimed_by = None
            self.claimed_at = None
            self.claim_token = None


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


def _application(
    *,
    student_id: str | None = "student-1",
    application_id: str = "app-1",
    session_id: str = "sess-1",
) -> Application:
    return Application(
        application_id=application_id,
        academy_id=ACADEMY_ID,
        parent_user_id="parent-1",
        parent_email="parent@example.com",
        status="PENDING_APPROVAL",
        parent_profile=ParentProfile(first_name="Pat", last_name="Parent"),
        child_profile=ChildProfile(first_name="Sam", last_name="Student"),
        selected_session_id=session_id,
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


def _second_session() -> Session:
    return _session().model_copy(update={"session_id": "sess-2", "title": "Junior B"})


@pytest.mark.asyncio
async def test_approve_reuses_existing_enrollment_without_reserving_seat() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([_session()])
    existing = Enrollment(
        enrollment_id=stable_ulid("registration-enrollment", "app-1", "student-1", "sess-1"),
        academy_id=ACADEMY_ID,
        session_id="sess-1",
        student_id="student-1",
        status="active",
        registration_application_id="app-1",
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
    assert detail.enrollment_id == existing.enrollment_id
    assert apps.saved[-1].enrollment_id == existing.enrollment_id
    recovered = await enrollments.get(existing.enrollment_id)
    assert recovered is not None
    assert recovered.enrolled_at == app.created_at


@pytest.mark.asyncio
async def test_approve_uses_parent_registration_date_for_enrollment() -> None:
    app = _application(student_id=None).model_copy(update={"created_at": NOW - timedelta(days=3)})
    enrollments = InMemoryEnrollments()
    review = AdminRegistrationReview(
        apps=InMemoryApplications(app),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert enrollments.created[0].enrolled_at == NOW - timedelta(days=3)


@pytest.mark.asyncio
async def test_pending_list_hides_child_who_already_has_active_enrollment() -> None:
    review = AdminRegistrationReview(
        apps=InMemoryApplications(_application(student_id=None)),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )
    review._student_registrations = ExistingStudentRegistrations(  # type: ignore[attr-defined]
        student_id="existing-student",
        active=True,
    )

    assert await review.list_pending() == []


@pytest.mark.asyncio
async def test_pending_list_routes_ambiguous_legacy_child_to_manual_review() -> None:
    review = AdminRegistrationReview(
        apps=InMemoryApplications(_application(student_id=None)),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        student_registrations=ExistingStudentRegistrations(ambiguous=True),
        clock=lambda: NOW,
    )

    rows = await review.list_pending()
    assert len(rows) == 1
    assert rows[0].status == "MANUAL_REVIEW"
    detail = await review.detail("app-1")
    assert detail.status == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_pending_list_recovers_stale_naive_datetime_review_claim() -> None:
    stale_app = _application().model_copy(
        update={
            "status": "APPROVING",
            "review_claimed_at": (NOW - timedelta(minutes=20)).replace(tzinfo=None),
        }
    )
    review = AdminRegistrationReview(
        apps=InMemoryApplications(stale_app),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    rows = await review.list_pending()

    assert len(rows) == 1
    assert rows[0].status == "APPROVING"
    detail = await review.detail("app-1")
    assert detail.status == "APPROVING"


@pytest.mark.asyncio
async def test_stale_approval_claim_cannot_switch_to_reject() -> None:
    stale_app = _application().model_copy(
        update={
            "status": "APPROVING",
            "review_claimed_at": NOW - timedelta(minutes=20),
            "review_claim_token": "expired-token",
        }
    )
    review = AdminRegistrationReview(
        apps=InMemoryApplications(stale_app),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    with pytest.raises(ApplicationNotEditable, match="not pending"):
        await review.reject(
            RejectRegistrationCommand(
                application_id="app-1", actor_id="admin-1", reason="duplicate"
            )
        )


@pytest.mark.asyncio
async def test_stale_waitlist_claim_cannot_switch_to_approve() -> None:
    stale_app = _application().model_copy(
        update={
            "status": "WAITLISTING",
            "review_claimed_at": NOW - timedelta(minutes=20),
            "review_claim_token": "expired-token",
        }
    )
    review = AdminRegistrationReview(
        apps=InMemoryApplications(stale_app),
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    with pytest.raises(ApplicationNotEditable, match="not pending"):
        await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))


@pytest.mark.asyncio
async def test_approve_does_not_upsert_using_stale_student_binding() -> None:
    app = _application(student_id="wrong-student")
    students = InMemoryStudents()
    review = AdminRegistrationReview(
        apps=InMemoryApplications(app),
        sessions=InMemorySessions([_session()]),
        students=students,
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        student_registrations=ExistingStudentRegistrations(student_id=None),
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert students.upserts[0].student_id != "wrong-student"


@pytest.mark.asyncio
async def test_approve_rejects_child_who_already_has_active_enrollment() -> None:
    sessions = InMemorySessions([_session()])
    enrollments = InMemoryEnrollments()
    review = AdminRegistrationReview(
        apps=InMemoryApplications(_application(student_id=None)),
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )
    review._student_registrations = ExistingStudentRegistrations(  # type: ignore[attr-defined]
        student_id="existing-student",
        active=True,
    )

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert sessions.reserve_calls == 0
    assert enrollments.created == []


@pytest.mark.asyncio
async def test_approve_rejects_session_override_that_differs_from_application() -> None:
    sessions = InMemorySessions([_session()])
    review = AdminRegistrationReview(
        apps=InMemoryApplications(_application(student_id=None)),
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    with pytest.raises(ApplicationNotEditable, match="session changed"):
        await review.approve(
            ApproveRegistrationCommand(
                application_id="app-1",
                actor_id="admin-1",
                session_id="different-session",
            )
        )

    assert sessions.reserve_calls == 0


@pytest.mark.asyncio
async def test_repeated_approval_is_idempotent_and_reserves_one_seat() -> None:
    app = _application(student_id=None)
    sessions = InMemorySessions([_session()])
    enrollments = InMemoryEnrollments()
    review = AdminRegistrationReview(
        apps=InMemoryApplications(app),
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    results = await asyncio.gather(
        review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")),
        review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")),
        return_exceptions=True,
    )

    assert all(not isinstance(result, Exception) for result in results)
    assert results[0].enrollment_id == results[1].enrollment_id  # type: ignore[union-attr]
    assert len(enrollments.created) == 1
    assert sessions.reserve_calls == 1
    assert sessions.release_calls == 0


@pytest.mark.asyncio
async def test_concurrent_applications_for_same_child_allow_only_one_enrollment() -> None:
    first_app = _application(application_id="app-1", session_id="sess-1", student_id=None)
    second_app = _application(application_id="app-2", session_id="sess-2", student_id=None)
    registrations = ExistingStudentRegistrations(student_id="student-1")
    sessions = InMemorySessions([_session(), _second_session()])
    enrollments = RegistrationTrackingEnrollments(registrations)
    review = AdminRegistrationReview(
        apps=InMemoryApplications([first_app, second_app]),
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        student_registrations=registrations,
        clock=lambda: NOW,
    )

    results = await asyncio.gather(
        review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")),
        review.approve(ApproveRegistrationCommand(application_id="app-2", actor_id="admin-1")),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ApplicationNotEditable) for result in results) == 1
    assert len(enrollments.created) == 1


@pytest.mark.asyncio
async def test_concurrent_approve_and_reject_allow_only_one_decision() -> None:
    apps = InMemoryApplications(_application(student_id=None))
    review = AdminRegistrationReview(
        apps=apps,
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    results = await asyncio.gather(
        review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")),
        review.reject(
            RejectRegistrationCommand(
                application_id="app-1", actor_id="admin-2", reason="duplicate"
            )
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, ApplicationNotEditable) for result in results) == 1
    assert apps.apps["app-1"].status in {"APPROVED", "DECLINED"}


@pytest.mark.asyncio
async def test_approve_recovers_pending_application_after_enrollment_was_created() -> None:
    app = _application(student_id=None)
    enrollment_id = stable_ulid("registration-enrollment", "app-1", "app-1", "sess-1")
    existing = Enrollment(
        enrollment_id=enrollment_id,
        academy_id=ACADEMY_ID,
        session_id="sess-1",
        student_id="app-1",
        status="active",
        enrolled_at=app.created_at,
        created_at=NOW,
        registration_application_id="app-1",
    )
    sessions = InMemorySessions([_session()])
    apps = InMemoryApplications(app)
    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments([existing]),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )
    review._student_registrations = ExistingStudentRegistrations(  # type: ignore[attr-defined]
        student_id="app-1",
        active=True,
        enrollment_id=enrollment_id,
    )

    detail = await review.approve(
        ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")
    )

    assert detail.status == "APPROVED"
    assert detail.enrollment_id == enrollment_id
    assert sessions.reserve_calls == 0


@pytest.mark.asyncio
async def test_approve_stamps_skip_period_for_zero_quote_application() -> None:
    app = _application(student_id="student-1").model_copy(update={"zero_quote_period": "2026-07"})
    apps = InMemoryApplications(app)
    enrollments = InMemoryEnrollments()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    detail = await review.approve(
        ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")
    )

    assert enrollments.skip_periods[detail.enrollment_id] == ["2026-07"]


@pytest.mark.asyncio
async def test_approve_does_not_stamp_skip_period_for_normal_application() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    enrollments = InMemoryEnrollments()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=enrollments,
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert enrollments.skip_periods == {}


@pytest.mark.asyncio
async def test_approve_writes_per_student_waiver_signature_from_registration_acceptance() -> None:
    app = _application(student_id="student-1").model_copy(
        update={
            "waiver_acceptance": WaiverAcceptance(
                waiver_template_id="wt-2026",
                waiver_version="2026.1",
                content_hash="hash-2026",
                accepted_at=NOW - timedelta(hours=1),
            )
        }
    )
    apps = InMemoryApplications(app)
    signatures = InMemoryWaiverSignatures()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        waiver_signatures=signatures,
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert len(signatures.saved) == 1
    signature = signatures.saved[0]
    assert signature.academy_id == ACADEMY_ID
    assert signature.waiver_template_id == "wt-2026"
    assert signature.student_id == "student-1"
    assert signature.parent_user_id == "parent-1"
    assert signature.signed_at == NOW - timedelta(hours=1)
    assert signature.signer_name == "Pat Parent"
    assert str(signature.signer_email) == "parent@example.com"
    assert signature.content_hash == "hash-2026"


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


@pytest.mark.asyncio
async def test_waitlist_rejects_child_who_already_has_active_enrollment() -> None:
    sessions = InMemorySessions([_session()])
    waitlist = InMemoryWaitlist()
    review = AdminRegistrationReview(
        apps=InMemoryApplications(_application(student_id=None)),
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=waitlist,
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )
    review._student_registrations = ExistingStudentRegistrations(  # type: ignore[attr-defined]
        student_id="existing-student",
        active=True,
    )

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await review.waitlist(
            WaitlistRegistrationCommand(application_id="app-1", actor_id="admin-1")
        )

    assert waitlist.entries == []


# --- R3 conversion tracking hook (Task 7) -------------------------------------


class _FakeTrialConversion:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def execute(self, *, parent_user_id: str, application_id: str) -> None:
        self.calls.append((parent_user_id, application_id))


class _FailingTrialConversion:
    async def execute(self, *, parent_user_id: str, application_id: str) -> None:
        raise RuntimeError("trial bookkeeping unavailable")


@pytest.mark.asyncio
async def test_approve_calls_trial_conversion_hook_with_parent_and_application() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([_session()])
    trial_conversion = _FakeTrialConversion()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        trial_conversion=trial_conversion,
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert trial_conversion.calls == [("parent-1", "app-1")]


@pytest.mark.asyncio
async def test_approve_without_trial_conversion_wired_does_not_raise() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([_session()])

    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        clock=lambda: NOW,
    )

    detail = await review.approve(
        ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")
    )

    assert detail.status == "APPROVED"


@pytest.mark.asyncio
async def test_approve_succeeds_when_optional_trial_linking_fails() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    review = AdminRegistrationReview(
        apps=apps,
        sessions=InMemorySessions([_session()]),
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        trial_conversion=_FailingTrialConversion(),
        clock=lambda: NOW,
    )

    detail = await review.approve(
        ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1")
    )

    assert detail.status == "APPROVED"
    assert apps.saved[-1].status == "APPROVED"


@pytest.mark.asyncio
async def test_approve_idempotent_replay_does_not_call_trial_conversion_again() -> None:
    app = _application(student_id="student-1")
    apps = InMemoryApplications(app)
    sessions = InMemorySessions([_session()])
    trial_conversion = _FakeTrialConversion()

    review = AdminRegistrationReview(
        apps=apps,
        sessions=sessions,
        students=InMemoryStudents(),
        enrollments=InMemoryEnrollments(),
        waitlist=InMemoryWaitlist(),
        academy_id=ACADEMY_ID,
        trial_conversion=trial_conversion,
        clock=lambda: NOW,
    )

    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))
    # Replaying approve() on an already-APPROVED application with an
    # enrollment_id hits the idempotency early-return, which must NOT
    # re-trigger conversion linking.
    await review.approve(ApproveRegistrationCommand(application_id="app-1", actor_id="admin-1"))

    assert trial_conversion.calls == [("parent-1", "app-1")]
