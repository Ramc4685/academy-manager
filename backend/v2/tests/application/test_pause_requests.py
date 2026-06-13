from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
    RequestEnrollmentPause,
    RequestEnrollmentPauseCommand,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


def test_fixed_pause_requires_resume_on() -> None:
    with pytest.raises(ValidationError, match="resume_on is required"):
        PauseRequest(
            pause_request_id="pause-1",
            enrollment_id="enr-1",
            parent_id="parent-1",
            pause_kind="fixed",
            reason="summer break",
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )


def test_indefinite_pause_rejects_resume_on() -> None:
    with pytest.raises(ValidationError, match="resume_on is only allowed"):
        PauseRequest(
            pause_request_id="pause-1",
            enrollment_id="enr-1",
            parent_id="parent-1",
            pause_kind="indefinite",
            resume_on=date(2026, 7, 1),
            reason="not sure",
            created_at=datetime(2026, 6, 3, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_request_pause_derives_legacy_period_from_resume_on() -> None:
    repo = _FakePauseRequests()
    use_case = RequestEnrollmentPause(pause_requests=repo)

    request = await use_case.execute(
        RequestEnrollmentPauseCommand(
            parent_id="parent-1",
            enrollment_id="enr-1",
            pause_kind="fixed",
            resume_on=date(2026, 7, 15),
            reason="summer travel",
        )
    )

    assert request.pause_kind == "fixed"
    assert request.resume_on == date(2026, 7, 15)
    assert request.period == "2026-07"


@pytest.mark.asyncio
async def test_mongo_pause_request_round_trips_pause_kind_and_resume_on() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["pause-requests-contract"]
    repo = MongoPauseRequestRepository(db)
    request = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="fixed",
        resume_on=date(2026, 7, 15),
        reason="summer travel",
        created_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    with tenant_scope("acad-1"):
        await repo.add(request)
        loaded = await repo.get("pause-1")

    assert loaded is not None
    assert loaded.pause_kind == "fixed"
    assert loaded.resume_on == date(2026, 7, 15)
    assert loaded.period == "2026-07"


@pytest.mark.asyncio
async def test_mongo_pending_pause_requests_include_admin_context() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["pause-requests-admin-context"]
    repo = MongoPauseRequestRepository(db)
    request = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="fixed",
        resume_on=date(2026, 7, 15),
        reason="summer travel",
        created_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    with tenant_scope("acad-1"):
        await db.enrollments.insert_one(
            {
                "academy_id": "acad-1",
                "enrollment_id": "enr-1",
                "student_id": "student-1",
                "session_id": "session-1",
                "status": "active",
            }
        )
        await db.students.insert_one(
            {
                "academy_id": "acad-1",
                "student_id": "student-1",
                "parent_id": "parent-1",
                "full_name": "Aadhya Abhishek",
            }
        )
        await db.sessions.insert_one(
            {
                "academy_id": "acad-1",
                "session_id": "session-1",
                "title": "Junior Foundations",
                "location": "Court 2",
                "start_at": datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
                "end_at": datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
            }
        )
        await db.users.insert_one(
            {
                "academy_id": "acad-1",
                "user_id": "parent-1",
                "display_name": "Abhishek Ajithkumar",
                "email": "abhishek@example.com",
            }
        )
        await repo.add(request)
        [loaded] = await repo.list_pending()

    assert loaded.parent_name == "Abhishek Ajithkumar"
    assert loaded.parent_email == "abhishek@example.com"
    assert loaded.student_id == "student-1"
    assert loaded.student_name == "Aadhya Abhishek"
    assert loaded.session_id == "session-1"
    assert loaded.session_title == "Junior Foundations"
    assert loaded.session_location == "Court 2"
    assert loaded.session_start_at == datetime(2026, 6, 4, 23, 0)


@pytest.mark.asyncio
async def test_mongo_pending_pause_requests_resolves_parent_without_academy_id() -> None:
    """Regression: parent lookup previously included academy_id which excluded
    cross-academy user documents that lack the field."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["pause-requests-parent-no-academy"]
    repo = MongoPauseRequestRepository(db)
    request = PauseRequest(
        pause_request_id="pause-2",
        enrollment_id="enr-2",
        parent_id="firebase-uid-abc",
        pause_kind="fixed",
        resume_on=date(2026, 7, 15),
        reason="summer",
        created_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    with tenant_scope("acad-1"):
        await db.enrollments.insert_one(
            {
                "academy_id": "acad-1",
                "enrollment_id": "enr-2",
                "student_id": "student-2",
                "session_id": "session-2",
                "status": "active",
            }
        )
        await db.students.insert_one(
            {
                "academy_id": "acad-1",
                "student_id": "student-2",
                "parent_id": "firebase-uid-abc",
                "full_name": "Test Student",
            }
        )
        # User doc has NO academy_id — mirrors production cross-academy users collection.
        await db.users.insert_one(
            {
                "firebase_uid": "firebase-uid-abc",
                "display_name": "Real Parent Name",
                "email": "realparent@example.com",
            }
        )
        await repo.add(request)
        [loaded] = await repo.list_pending()

    assert loaded.parent_name == "Real Parent Name"
    assert loaded.parent_email == "realparent@example.com"


@pytest.mark.asyncio
async def test_mongo_pending_pause_requests_falls_back_to_billing_enrollment() -> None:
    """Regression: only enrollments was checked; billing-flow pause requests store
    enrollment_id from student_billing_enrollments which was never joined."""
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["pause-requests-billing-fallback"]
    repo = MongoPauseRequestRepository(db)
    request = PauseRequest(
        pause_request_id="pause-3",
        enrollment_id="billing-enr-1",
        parent_id="parent-3",
        pause_kind="indefinite",
        reason="surgery",
        created_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    with tenant_scope("acad-1"):
        # No row in enrollments — only in student_billing_enrollments.
        await db.student_billing_enrollments.insert_one(
            {
                "academy_id": "acad-1",
                "enrollment_id": "billing-enr-1",
                "student_id": "student-3",
                "session_type_id": "st-1",
            }
        )
        await db.students.insert_one(
            {
                "academy_id": "acad-1",
                "student_id": "student-3",
                "full_name": "Aadhya Abhishek",
            }
        )
        await db.session_types.insert_one(
            {
                "academy_id": "acad-1",
                "session_type_id": "st-1",
                "name": "Junior Foundations",
            }
        )
        await repo.add(request)
        [loaded] = await repo.list_pending()

    assert loaded.student_name == "Aadhya Abhishek"
    assert loaded.session_title == "Junior Foundations"
    assert loaded.student_id == "student-3"


class _FakePauseRequests:
    async def add(self, request: PauseRequest) -> None:
        self.request = request

    async def enrollment_belongs_to_parent(self, enrollment_id: str, parent_id: str) -> bool:
        return True
