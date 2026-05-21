"""Contract tests for occurrence-keyed attendance uniqueness."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.coaching.domain.errors import ConflictAttendanceExists
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.tenancy.context import tenant_scope


def _attendance(attendance_id: str, occurrence_id: str) -> Attendance:
    return Attendance(
        attendance_id=attendance_id,
        academy_id="test-academy",
        occurrence_id=occurrence_id,
        session_id="sess-recurring",
        student_id="st1",
        marked_by="coach-1",
        marked_at=datetime.now(timezone.utc),
        status="present",
    )


@pytest.mark.asyncio
async def test_same_student_can_be_marked_for_multiple_occurrences(db) -> None:
    await run_pending_migrations(db)
    repo = MongoAttendanceRepository(db)

    with tenant_scope("test-academy"):
        await repo.save(_attendance("mut-1", "occ-2026-06-01"))
        await repo.save(_attendance("mut-2", "occ-2026-06-08"))

        assert await repo.find_existing("occ-2026-06-01", "st1") is not None
        assert await repo.find_existing("occ-2026-06-08", "st1") is not None


@pytest.mark.asyncio
async def test_duplicate_student_mark_for_same_occurrence_conflicts(db) -> None:
    await run_pending_migrations(db)
    repo = MongoAttendanceRepository(db)

    with tenant_scope("test-academy"):
        await repo.save(_attendance("mut-1", "occ-2026-06-01"))

        with pytest.raises(ConflictAttendanceExists) as exc_info:
            await repo.save(_attendance("mut-2", "occ-2026-06-01"))

    assert exc_info.value.details["existing_attendance_id"] == "mut-1"
