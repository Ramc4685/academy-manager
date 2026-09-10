"""MongoEnrollmentWriter contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)


@pytest.mark.asyncio
async def test_find_for_session_student_prefers_resumable_enrollment(db, acad) -> None:
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-cancelled",
                "session_id": "sess-1",
                "student_id": "stu-1",
                "status": "cancelled",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-paused",
                "session_id": "sess-1",
                "student_id": "stu-1",
                "status": "paused",
            },
        ]
    )
    repo = MongoEnrollmentWriter(db)

    result = await repo.find_for_session_student("sess-1", "stu-1")

    assert result is not None
    assert result.enrollment_id == "enr-paused"
    assert result.status == "paused"


@pytest.mark.asyncio
async def test_create_if_absent_is_atomic_for_registration_replay(db, acad) -> None:
    repo = MongoEnrollmentWriter(db)
    enrollment = Enrollment(
        enrollment_id="registration-app-1",
        academy_id=acad,
        session_id="sess-1",
        student_id="student-1",
        status="active",
        enrolled_at=datetime(2026, 7, 9, tzinfo=UTC),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        registration_application_id="app-1",
    )

    first = await repo.create_if_absent(enrollment)
    second = await repo.create_if_absent(enrollment)

    assert first is True
    assert second is False
    stored = await repo.get("registration-app-1")
    assert stored is not None
    assert stored.registration_application_id == "app-1"
    assert (
        await db["enrollments"].count_documents(
            {"academy_id": acad, "enrollment_id": "registration-app-1"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_set_enrolled_at_if_missing_repairs_legacy_registration_date(db, acad) -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "legacy-enrollment",
            "session_id": "sess-1",
            "student_id": "student-1",
            "status": "active",
            "enrolled_at": None,
        }
    )
    repo = MongoEnrollmentWriter(db)
    registered_at = datetime(2026, 7, 9, tzinfo=UTC)

    await repo.set_enrolled_at_if_missing("legacy-enrollment", registered_at)

    stored = await repo.get("legacy-enrollment")
    assert stored is not None
    assert stored.enrolled_at == registered_at.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_mark_withdrawn_if_open_is_a_cas_that_returns_the_pre_image(db, acad) -> None:
    """Issue #670: the flip is the seat token — exactly one caller gets the
    `active` pre-image, a retry or a concurrent submit gets None."""
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-active",
                "session_id": "s",
                "student_id": "a",
                "status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-paused",
                "session_id": "s",
                "student_id": "b",
                "status": "paused",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-cancelled",
                "session_id": "s",
                "student_id": "c",
                "status": "cancelled",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-legacy",
                "session_id": "s",
                "student_id": "d",
            },
        ]
    )
    repo = MongoEnrollmentWriter(db)
    when = datetime(2026, 9, 15, tzinfo=UTC)

    first = await repo.mark_withdrawn_if_open("enr-active", withdrawal_date=when)
    second = await repo.mark_withdrawn_if_open("enr-active", withdrawal_date=when)

    assert first is not None and first.status == "active"
    assert second is None
    doc = await db["enrollments"].find_one({"enrollment_id": "enr-active"})
    assert doc is not None
    # Issue #699: canonical spelling is "dropped" (was "withdrawn").
    assert doc["status"] == "dropped"
    # mongomock hands naive datetimes back; the instant is what matters.
    assert doc["withdrawal_date"].replace(tzinfo=UTC) == when

    paused = await repo.mark_withdrawn_if_open("enr-paused", withdrawal_date=when)
    assert paused is not None and paused.status == "paused"
    assert await repo.mark_withdrawn_if_open("enr-cancelled", withdrawal_date=when) is None
    # a legacy row with no status field reads as active everywhere; it is open too
    legacy = await repo.mark_withdrawn_if_open("enr-legacy", withdrawal_date=when)
    assert legacy is not None and legacy.status == "active"
    assert await repo.mark_withdrawn_if_open("missing", withdrawal_date=when) is None
    assert await db["enrollments"].count_documents({"status": "cancelled"}) == 1
