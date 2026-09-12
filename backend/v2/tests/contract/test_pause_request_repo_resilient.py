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

from datetime import UTC, date, datetime

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


def test_coerced_legacy_row_never_reviews_before_it_was_requested():
    """#616: prod showed "Review Jun 1, 2026" on a request made Jun 2, 2026.

    The display fallback derived the review date from the pause period (first
    of that month) with no floor at the row's own ``created_at``.
    """
    coerced = MongoPauseRequestRepository._to_domain(
        dict(
            pause_request_id="pr-legacy",
            enrollment_id="e1",
            parent_id="p1",
            period="2026-06",
            status="pending",
            # fixed (the default) with no resume_on: fails the window
            # invariant, so the read coerces it for display.
            created_at=datetime(2026, 6, 2, 14, 30, tzinfo=UTC),
        )
    )

    assert coerced.review_on == date(2026, 6, 2)
    assert coerced.review_on >= coerced.created_at.date()


async def test_list_pending_enriches_rows_with_parent_student_and_session(db, acad):
    """#616 row-enrichment: the admin queue must show names, not raw ids.

    The enrichment lives behind the ``PauseRequestRepository`` port, in
    ``list_pending`` — ``ListAdminPauseRequests`` deliberately holds only the
    repo. This pins that the read resolves the parent through their Firebase
    uid, the student, and the session, so the queue never renders a raw uid,
    "Student: Unknown", or a bare enrollment id.
    """
    repo = MongoPauseRequestRepository(db)
    await db["enrollments"].insert_one(
        dict(academy_id=acad, enrollment_id="e1", student_id="s1", session_id="sess1")
    )
    await db["students"].insert_one(
        dict(
            academy_id=acad,
            student_id="s1",
            first_name="Asha",
            last_name="Rao",
            parent_id="firebase-uid-1",
        )
    )
    await db["sessions"].insert_one(
        dict(
            academy_id=acad,
            session_id="sess1",
            title="Tuesday Juniors",
            location="Court 3",
        )
    )
    await db["users"].insert_one(
        dict(firebase_uid="firebase-uid-1", first_name="Priya", last_name="Rao", email="p@x.test")
    )
    await db["pause_requests"].insert_one(
        dict(
            academy_id=acad,
            pause_request_id="pr-1",
            enrollment_id="e1",
            parent_id="firebase-uid-1",
            period="2026-08",
            status="pending",
            pause_kind="fixed",
            resume_on="2026-08-01",
            created_at=datetime.now(UTC),
        )
    )

    (row,) = await repo.list_pending()

    assert row.parent_name == "Priya Rao"
    assert row.parent_email == "p@x.test"
    assert row.student_name == "Asha Rao"
    assert row.session_title == "Tuesday Juniors"
    assert row.session_location == "Court 3"
