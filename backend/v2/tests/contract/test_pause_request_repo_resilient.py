"""Contract tests: pause-request reads tolerate legacy/invalid stored docs.

Regression for the admin `GET /api/v2/admin/pause-requests` 500: a single
stored ``pause_requests`` doc that violates the ``PauseRequest`` write-time
window invariant (e.g. a legacy doc with no ``pause_kind`` and no
``resume_on`` — a shape the Mongo ``$jsonSchema`` from migration 0133 still
permits) used to raise ``ValidationError`` inside ``list_pending`` and take
down the whole list. Reads must now surface every pending doc so admins can
still see and action it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)


async def test_list_pending_tolerates_legacy_doc_without_resume_on(db, acad):
    repo = MongoPauseRequestRepository(db)
    await db["pause_requests"].insert_many(
        [
            dict(
                academy_id=acad,
                pause_request_id="pr-ok",
                enrollment_id="e1",
                parent_id="p1",
                period="2026-08",
                status="pending",
                pause_kind="fixed",
                resume_on="2026-08-01",
                created_at=datetime.now(UTC),
            ),
            # Legacy/edge doc: no pause_kind (defaults to fixed) and no
            # resume_on. Permitted by the Mongo schema; violates the domain
            # write invariant. Must not 500 the list.
            dict(
                academy_id=acad,
                pause_request_id="pr-legacy",
                enrollment_id="e2",
                parent_id="p2",
                period="2026-08",
                status="pending",
                created_at=datetime.now(UTC),
            ),
        ]
    )

    rows = await repo.list_pending()

    # Both requests surface — the legacy one is not silently dropped.
    assert {r.pause_request_id for r in rows} == {"pr-ok", "pr-legacy"}


async def test_list_for_parent_tolerates_legacy_doc(db, acad):
    repo = MongoPauseRequestRepository(db)
    await db["pause_requests"].insert_one(
        dict(
            academy_id=acad,
            pause_request_id="pr-legacy",
            enrollment_id="e2",
            parent_id="p9",
            period="2026-08",
            status="pending",
            created_at=datetime.now(UTC),
        )
    )

    rows = await repo.list_for_parent("p9")

    assert [r.pause_request_id for r in rows] == ["pr-legacy"]
