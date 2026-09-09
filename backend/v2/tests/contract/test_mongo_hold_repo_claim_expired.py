"""Defect #4 — ``MongoHoldRepository.claim_expired``'s CAS filter must
re-check expiry, not just ``{status: "held", hold_reclaim_claimed_at: None}``.

Reproduction: ``ExpireDueHolds.execute`` snapshots overdue rows via
``list_expired(now=T1)``, then claims each one by id via ``claim_expired``.
Between the snapshot and the claim, the family can Return (``held -> active``)
and be re-Held (``active -> held``) with a FRESH ``hold_expires_at`` — the
row still has ``status == "held"`` and ``hold_reclaim_claimed_at is None``,
so the old filter (no expiry predicate at all) still matches it and the
sweep drops a family who is no longer overdue.

The fix folds ``hold_expires_at: {"$lte": now}`` into the CAS filter itself,
so the claim fails once the row is no longer actually expired — exactly the
way ``claim_longest_held`` fails once a row is no longer ``status == "held"``.

Runs against a real (mongomock) ``find_one_and_update`` because this is a
claim about the atomic filter, not about the fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.composition.enrollment_holds import MongoHoldRepository
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-claim-expired"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _held_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "enrollment_id": "enr-1",
        "academy_id": ACADEMY_ID,
        "session_id": "sess-1",
        "student_id": "stu-1",
        "status": "held",
        "hold_started_at": NOW - timedelta(days=10),
        "hold_expires_at": NOW - timedelta(hours=1),  # expired at snapshot time
        "hold_reclaim_claimed_at": None,
        "hold_reclaim_for": None,
        "hold_seq": 1,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_claim_expired_wins_when_the_row_is_still_actually_expired(db) -> None:
    """Control: nothing raced the sweep — the claim must still succeed."""
    await db["enrollments"].insert_one(_held_row())
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldRepository(db)
        claimed = await repo.claim_expired(
            enrollment_id="enr-1", now=NOW, requested_by="hold_expiry"
        )

    assert claimed is not None
    assert claimed.enrollment_id == "enr-1"
    doc = await db["enrollments"].find_one({"enrollment_id": "enr-1"})
    assert doc["status"] == "reclaim_pending"


@pytest.mark.asyncio
async def test_claim_expired_loses_the_race_against_a_return_and_re_hold(db) -> None:
    """The reproduction: between list_expired's snapshot and this claim, the
    family returned and was re-Held with a hold_expires_at 60 days out. The
    CAS must refuse — the pre-fix filter (no hold_expires_at predicate)
    would wrongly win here and drop a family who is no longer overdue."""
    await db["enrollments"].insert_one(
        _held_row(hold_expires_at=NOW + timedelta(days=60), hold_started_at=NOW, hold_seq=2)
    )
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldRepository(db)
        claimed = await repo.claim_expired(
            enrollment_id="enr-1", now=NOW, requested_by="hold_expiry"
        )

    assert claimed is None, (
        "claim_expired matched a row whose hold_expires_at is in the future — "
        "the CAS filter is missing the hold_expires_at <= now predicate"
    )
    doc = await db["enrollments"].find_one({"enrollment_id": "enr-1"})
    # The re-held row must be completely untouched by the losing claim.
    assert doc["status"] == "held"
    assert doc["hold_reclaim_claimed_at"] is None
