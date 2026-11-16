"""Attendance replays converge on a real ``mongod`` (unique attendance index).

A mark or batch that committed rows but never stored its idempotency record
(timeout, crash, a racing replay) must succeed on replay instead of 409ing
on its own rows: the coach's offline queue would otherwise park a mark that
was applied in the Needs-review tray, and a half-written batch could never be
finished. A row from a different mutation is still a conflict.

Synthetic ids only. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.coaching_lookups import (
    EnrollmentLookupAdapter,
    EnrollmentOccurrenceLookup,
)
from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkAttendanceEntry,
    BulkMarkAttendance,
    BulkMarkAttendanceCommand,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendance,
    MarkAttendanceCommand,
)
from backend.v2.contexts.coaching.domain.errors import ConflictAttendanceExists
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.idempotency_fakes import ClaimableStore

ACADEMY = "acad-replay"
COACH = "coach-replay"
NOW = datetime.now(UTC)


async def _seed(db: Any) -> None:
    await db["session_occurrences"].insert_one(
        {
            "academy_id": ACADEMY,
            "occurrence_id": "occ-replay",
            "session_id": "ses-replay",
            "start_at": NOW - timedelta(hours=1),
            "end_at": NOW,
            "status": "scheduled",
            "scheduled_coach_id": COACH,
        }
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "enrollment_id": f"enr-{s}",
                "session_id": "ses-replay",
                "student_id": s,
                "status": "active",
                "enrolled_at": NOW - timedelta(days=30),
            }
            for s in ("stu-a", "stu-b")
        ]
    )


def _deps(db: Any, idempotency: Any) -> dict[str, Any]:
    return {
        "attendance_repo": MongoAttendanceRepository(db),
        "occurrence_lookup": EnrollmentOccurrenceLookup(MongoSessionOccurrenceRepository(db)),
        "enrollment_lookup": EnrollmentLookupAdapter(
            MongoEnrollmentRepository(db), MongoOccurrenceRosterRepository(db)
        ),
        "outbox": MongoOutbox(db),
        "idempotency_store": idempotency,
        "academy_id": lambda: ACADEMY,
    }


class _LostRecords(ClaimableStore):
    """An idempotency store whose writes never land (put failed after commit)."""

    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def put(self, key: str, value: dict[str, Any]) -> None:
        return None

    async def claim(self, key: str) -> bool:
        return True


def _bulk(mutation_id: str, *students: str) -> BulkMarkAttendanceCommand:
    return BulkMarkAttendanceCommand(
        mutation_id=mutation_id,
        occurrence_id="occ-replay",
        session_id="ses-replay",
        entries=[BulkAttendanceEntry(student_id=s, status="present") for s in students],
    )


@pytest.mark.asyncio
async def test_single_mark_replay_after_lost_idempotency_record_succeeds(real_db: Any) -> None:
    await _seed(real_db)
    cmd = MarkAttendanceCommand(
        mutation_id="01JREPLAYMARK000000000000A",
        occurrence_id="occ-replay",
        session_id="ses-replay",
        student_id="stu-a",
        status="present",
    )
    with tenant_scope(ACADEMY):
        uc = MarkAttendance(**_deps(real_db, _LostRecords()))
        first = await uc.execute(cmd, COACH)
        replay = await uc.execute(cmd, COACH)

    assert replay.attendance_id == first.attendance_id
    assert await real_db["attendance"].count_documents({"academy_id": ACADEMY}) == 1


@pytest.mark.asyncio
async def test_interrupted_bulk_batch_replay_finishes_and_stays_single(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        # The first run was cut off after writing stu-a's row only.
        await BulkMarkAttendance(**_deps(real_db, _LostRecords())).execute(
            _bulk("01JREPLAYBULK000000000000A", "stu-a"), COACH
        )
        uc = BulkMarkAttendance(**_deps(real_db, MongoIdempotencyStore(real_db)))
        result = await uc.execute(_bulk("01JREPLAYBULK000000000000A", "stu-a", "stu-b"), COACH)

    assert [r.student_id for r in result.results] == ["stu-a", "stu-b"]
    rows = await real_db["attendance"].find({"academy_id": ACADEMY}).to_list(None)
    assert sorted(r["attendance_id"] for r in rows) == [
        "01JREPLAYBULK000000000000A:0",
        "01JREPLAYBULK000000000000A:1",
    ]


@pytest.mark.asyncio
async def test_bulk_row_from_another_mutation_still_conflicts(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        await BulkMarkAttendance(**_deps(real_db, _LostRecords())).execute(
            _bulk("01JREPLAYOTHER00000000000A", "stu-a"), COACH
        )
        with pytest.raises(ConflictAttendanceExists):
            await BulkMarkAttendance(**_deps(real_db, _LostRecords())).execute(
                _bulk("01JREPLAYBULK000000000000B", "stu-a", "stu-b"), COACH
            )
    assert await real_db["attendance"].count_documents({"academy_id": ACADEMY}) == 1


@pytest.mark.asyncio
async def test_marked_at_reads_back_as_utc(real_db: Any) -> None:
    # Motor returns naive datetimes; a naive marked_at serializes without
    # ``Z`` and the phone shifts its 48h correction lock by the UTC offset.
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        await MarkAttendance(**_deps(real_db, _LostRecords())).execute(
            MarkAttendanceCommand(
                mutation_id="01JREPLAYUTC00000000000000",
                occurrence_id="occ-replay",
                session_id="ses-replay",
                student_id="stu-a",
                status="present",
            ),
            COACH,
        )
        [row] = await MongoAttendanceRepository(real_db).list_for_occurrence("occ-replay")

    assert row.marked_at.utcoffset() == timedelta(0)
