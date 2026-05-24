"""MongoEnrollmentWriter contract tests."""

from __future__ import annotations

import pytest

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
