"""Re-opening make-ups and trials when a class date is cancelled (issue #671).

Both entitlements were granted against a specific occurrence. When the academy
calls that date off the one-time roster seat is deleted, so the entitlement has
to come back — and come back USABLE:

* a make-up re-opened with its original ``expires_at`` is flipped straight
  back to ``expired`` by the next sweep, and the family silently loses a
  make-up it had already been granted;
* a trial left ``approved`` against a cancelled occurrence has no seat, no
  admin queue entry and nothing to re-offer it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
    MongoMakeupRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-671"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LAPSED = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_reopened_makeup_gets_a_fresh_window_and_survives_the_sweep(db) -> None:
    await db["makeup_requests"].insert_one(
        {
            "academy_id": ACADEMY,
            "request_id": "mk-1",
            "student_id": "st-1",
            "parent_id": "par-1",
            "missed_occurrence_id": "occ-missed",
            "requested_target_occurrence_id": "occ-1",
            "approved_target_occurrence_id": "occ-1",
            "status": "approved",
            "decided_by": "admin-1",
            "decided_at": datetime(2026, 9, 5, tzinfo=UTC),
            # Granted under a window that has ALREADY lapsed by the time the
            # class it was approved onto was due to run.
            "expires_at": LAPSED,
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )
    with tenant_scope(ACADEMY):
        repo = MongoMakeupRequestRepository(db)

        reopened = await repo.reopen_for_target_occurrence(
            "occ-1", expires_at=NOW + timedelta(days=30)
        )
        assert reopened == 1

        expired = await repo.expire_pending_before(NOW)
        assert expired == 0

    row = await db["makeup_requests"].find_one({"request_id": "mk-1"})
    assert row["status"] == "pending"
    assert row["approved_target_occurrence_id"] is None
    # mongomock strips the tzinfo on round-trip; compare naive UTC.
    assert row["expires_at"].replace(tzinfo=UTC) > NOW


@pytest.mark.asyncio
async def test_trials_assigned_to_the_cancelled_date_are_reopened(db) -> None:
    await db["trial_requests"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "request_id": "tr-1",
                "parent_user_id": "par-1",
                "student_ref": "existing",
                "student_id": "st-trial",
                "requested_session_id": "sess-1",
                "preferred_start": "2026-09-01",
                "preferred_end": "2026-09-30",
                "status": "approved",
                "assigned_occurrence_id": "occ-1",
                "decided_by": "admin-1",
                "decided_at": datetime(2026, 9, 5, tzinfo=UTC),
                "created_at": datetime(2026, 9, 1, tzinfo=UTC),
            },
            {
                "academy_id": ACADEMY,
                "request_id": "tr-2",
                "parent_user_id": "par-2",
                "student_ref": "existing",
                "student_id": "st-other",
                "requested_session_id": "sess-1",
                "preferred_start": "2026-09-01",
                "preferred_end": "2026-09-30",
                "status": "approved",
                "assigned_occurrence_id": "occ-2",
                "created_at": datetime(2026, 9, 1, tzinfo=UTC),
            },
        ]
    )
    with tenant_scope(ACADEMY):
        student_ids = await MongoTrialRequestRepository(db).reopen_for_assigned_occurrence("occ-1")

    assert student_ids == ["st-trial"]
    reopened = await db["trial_requests"].find_one({"request_id": "tr-1"})
    assert reopened["status"] == "pending"
    assert reopened["assigned_occurrence_id"] is None
    untouched = await db["trial_requests"].find_one({"request_id": "tr-2"})
    assert untouched["status"] == "approved"
    assert untouched["assigned_occurrence_id"] == "occ-2"


@pytest.mark.asyncio
async def test_another_academy_cannot_reopen_these_rows(db) -> None:
    await db["trial_requests"].insert_one(
        {
            "academy_id": ACADEMY,
            "request_id": "tr-1",
            "parent_user_id": "par-1",
            "student_ref": "existing",
            "student_id": "st-trial",
            "requested_session_id": "sess-1",
            "preferred_start": "2026-09-01",
            "preferred_end": "2026-09-30",
            "status": "approved",
            "assigned_occurrence_id": "occ-1",
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )
    with tenant_scope("other-academy"):
        assert await MongoTrialRequestRepository(db).reopen_for_assigned_occurrence("occ-1") == []

    row = await db["trial_requests"].find_one({"request_id": "tr-1"})
    assert row["status"] == "approved"
