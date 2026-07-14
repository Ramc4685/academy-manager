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
