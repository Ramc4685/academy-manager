"""Wave 1B contract test — server-side double-mark race.

Two devices, same coach, same (occurrence, student), distinct mutation_ids.
The unique index `(academy_id, occurrence_id, student_id)` must let the first
write succeed and reject the second.

Run after migration 0020 applies the unique index.
"""

from __future__ import annotations

from datetime import UTC

import pytest

from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


@pytest.mark.asyncio
async def test_unique_index_rejects_duplicate_occurrence_student(db) -> None:
    # mongomock-motor honors unique indexes; apply the migration via the
    # idempotent runner so we don't duplicate the index definition here.
    from backend.v2.migrations import run_pending_migrations

    await run_pending_migrations(db)

    with tenant_scope("test-academy"):
        repo = MongoAttendanceRepository(db)
        # First device: write succeeds.
        from datetime import datetime

        from backend.v2.contexts.coaching.domain.models import Attendance

        first = Attendance(
            attendance_id="mut-A",
            academy_id="test-academy",
            occurrence_id="occ-1",
            session_id="sess",
            student_id="st1",
            marked_by="coach",
            marked_at=datetime.now(UTC),
            status="present",
        )
        await repo.save(first)

        second = first.model_copy(update={"attendance_id": "mut-B", "status": "absent"})
        # The repo translates Mongo's DuplicateKeyError into the domain
        # `ConflictAttendanceExists` so the BFF returns 409 (not 500)
        # for offline-policy case #4. See PR review feedback on PR #18.
        from backend.v2.contexts.coaching.domain.errors import ConflictAttendanceExists

        with pytest.raises(ConflictAttendanceExists) as exc_info:
            await repo.save(second)
        assert exc_info.value.code == "Coaching.ConflictAttendanceExists"
        assert exc_info.value.details["existing_attendance_id"] == "mut-A"
