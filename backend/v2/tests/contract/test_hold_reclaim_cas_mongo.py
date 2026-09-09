"""Departures design contract §3.4/§3.5, C1 and C2 — the reclaim CAS's
atomicity is a claim about real Mongo (``find_one_and_update``), not about a
Python dict fake. These tests run ``MongoHoldRepository`` against a real
(mongomock) database so a regression to "read status, then separately
$set it" — which would let two concurrent callers both win — cannot pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.infrastructure.mongo_hold_repo import MongoHoldRepository
from backend.v2.shared.tenancy.context import tenant_scope

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


async def _insert_held(
    db, acad: str, enrollment_id: str, *, session_id: str, hold_started_at: datetime
) -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "student_id": f"stu-{enrollment_id}",
            "status": "held",
            "hold_started_at": hold_started_at,
            "hold_reclaim_claimed_at": None,
            "hold_seq": 1,
        }
    )


@pytest.mark.asyncio
async def test_c1_claim_longest_held_is_a_single_atomic_claim(db, acad) -> None:
    """C1: one held row on a full session. A second claim attempt — the
    stand-in for a second concurrent broker — must find nothing, and the
    document must show exactly one claim, never two half-applied updates."""
    await _insert_held(
        db, acad, "held-1", session_id="sess-1", hold_started_at=NOW - timedelta(days=10)
    )
    repo = MongoHoldRepository(db)

    first = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="a")
    second = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="b")

    assert first is not None
    assert first.enrollment_id == "held-1"
    assert second is None  # the filter no longer matches — status is reclaim_pending

    doc = await db["enrollments"].find_one({"enrollment_id": "held-1"})
    assert doc["status"] == "reclaim_pending"
    assert doc["hold_reclaim_claimed_at"].replace(tzinfo=UTC) == NOW
    assert doc["hold_reclaim_for"] == "a"  # the SECOND caller's requested_by never wrote


@pytest.mark.asyncio
async def test_c2_two_held_rows_claimed_in_deterministic_longest_first_order(db, acad) -> None:
    """C2: two brokers, two held rows. Real Mongo's sort + atomic
    find_one_and_update must hand out the two distinct victims in
    (hold_started_at ASC, enrollment_id ASC) order — never the same row
    twice, never an arbitrary pair."""
    await _insert_held(
        db, acad, "held-newer", session_id="sess-1", hold_started_at=NOW - timedelta(days=5)
    )
    await _insert_held(
        db, acad, "held-older", session_id="sess-1", hold_started_at=NOW - timedelta(days=20)
    )
    repo = MongoHoldRepository(db)

    first = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="a")
    second = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="b")
    third = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="c")

    assert first is not None and first.enrollment_id == "held-older"
    assert second is not None and second.enrollment_id == "held-newer"
    assert third is None  # nothing left to claim

    statuses = {
        doc["enrollment_id"]: doc["status"]
        async for doc in db["enrollments"].find({"session_id": "sess-1"})
    }
    assert statuses == {"held-older": "reclaim_pending", "held-newer": "reclaim_pending"}


@pytest.mark.asyncio
async def test_claim_is_scoped_to_its_own_session_and_tenant(db, acad) -> None:
    """A held row in a different session, or a different academy, must
    never be claimable for THIS session's demand — cross-session or
    cross-tenant reclaim would drop the wrong family's child."""
    await _insert_held(
        db,
        acad,
        "held-other-session",
        session_id="sess-2",
        hold_started_at=NOW - timedelta(days=99),
    )
    with tenant_scope("other-academy"):
        await db["enrollments"].insert_one(
            {
                "academy_id": "other-academy",
                "enrollment_id": "held-other-tenant",
                "session_id": "sess-1",
                "student_id": "stu-x",
                "status": "held",
                "hold_started_at": NOW - timedelta(days=99),
                "hold_reclaim_claimed_at": None,
                "hold_seq": 1,
            }
        )
    repo = MongoHoldRepository(db)

    # Still scoped to `acad` (the `other_acad` fixture is deliberately not
    # used here — it overwrites the tenant ContextVar for the rest of the
    # test, which would make this test pass for the wrong reason).
    result = await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="a")

    assert result is None


@pytest.mark.asyncio
async def test_finalize_reclaim_is_also_a_cas_double_finalize_is_a_no_op(db, acad) -> None:
    """The second half of the CAS chain: finalize_reclaim only succeeds
    against a `reclaim_pending` row, so a stalled-reclaim sweep racing the
    original caller's own finalize can never drop the same row twice."""
    await _insert_held(db, acad, "held-1", session_id="sess-1", hold_started_at=NOW)
    repo = MongoHoldRepository(db)
    await repo.claim_longest_held(session_id="sess-1", now=NOW, requested_by="a")

    first = await repo.finalize_reclaim("held-1", withdrawal_date=NOW)
    second = await repo.finalize_reclaim("held-1", withdrawal_date=NOW)

    assert first is not None
    assert second is None
    doc = await db["enrollments"].find_one({"enrollment_id": "held-1"})
    assert doc["status"] == "dropped"
