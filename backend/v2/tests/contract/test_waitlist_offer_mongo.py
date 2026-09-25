"""X2 against real Mongo: the offer-closing compare-and-set, and the parent's
own waitlist read (tenant- and family-scoped, with the validator from 0183
applied by the ``real_db`` fixture's migrations)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.composition.waitlist_offers import compose_list_parent_waitlist
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

NOW = datetime.now(UTC).replace(microsecond=0)


async def _row(db, acad, waitlist_id, *, parent_id="par-1", status="waiting", **extra):
    await db["waitlist"].insert_one(
        {
            "waitlist_id": waitlist_id,
            "academy_id": acad,
            "session_id": "sess-1",
            "student_id": f"stu-{waitlist_id}",
            "parent_id": parent_id,
            "joined_at": NOW - timedelta(days=10),
            "status": status,
            **extra,
        }
    )


@pytest.mark.asyncio
async def test_transition_status_is_a_compare_and_set(real_db) -> None:
    await _row(real_db, "acad-a", "wl-1", status="offered", offer_expires_at=NOW)
    repo = MongoWaitlistRepository(real_db)

    with tenant_scope("acad-a"):
        assert await repo.transition_status("wl-1", expected="offered", to="removed") is True
        # Second closer loses: the row already moved on.
        assert await repo.transition_status("wl-1", expected="offered", to="expired") is False
    doc = await real_db["waitlist"].find_one({"waitlist_id": "wl-1"})
    assert doc["status"] == "removed"


@pytest.mark.asyncio
async def test_transition_status_never_touches_another_tenants_row(real_db) -> None:
    await _row(real_db, "acad-b", "wl-b", status="offered", offer_expires_at=NOW)
    repo = MongoWaitlistRepository(real_db)

    with tenant_scope("acad-a"):
        assert await repo.transition_status("wl-b", expected="offered", to="removed") is False
    doc = await real_db["waitlist"].find_one({"waitlist_id": "wl-b"})
    assert doc["status"] == "offered"


@pytest.mark.asyncio
async def test_parent_list_is_scoped_ordered_and_hides_old_or_closed_rows(real_db) -> None:
    await real_db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": "acad-a",
            "title": "Beginners",
            "location": "Court 2",
            "start_at": NOW,
            "end_at": NOW + timedelta(hours=1),
            "capacity": 10,
            "status": "scheduled",
        }
    )
    await real_db["students"].insert_one(
        {
            "student_id": "stu-offer",
            "academy_id": "acad-a",
            "parent_id": "par-1",
            "full_name": "Asha Rao",
        }
    )
    await _row(real_db, "acad-a", "wait")
    await _row(
        real_db, "acad-a", "offer", status="offered", offer_expires_at=NOW + timedelta(days=2)
    )
    await _row(
        real_db,
        "acad-a",
        "recent-expired",
        status="expired",
        offer_expires_at=NOW - timedelta(days=1),
    )
    await _row(
        real_db,
        "acad-a",
        "old-expired",
        status="expired",
        offer_expires_at=NOW - timedelta(days=30),
    )
    await _row(real_db, "acad-a", "gone", status="removed")
    await _row(
        real_db, "acad-a", "stranger", parent_id="par-2", status="offered", offer_expires_at=NOW
    )
    await _row(real_db, "acad-b", "other-tenant", status="offered", offer_expires_at=NOW)

    list_rows = compose_list_parent_waitlist(real_db)
    with tenant_scope("acad-a"):
        rows = await list_rows("par-1")

    assert [r["waitlist_id"] for r in rows] == ["offer", "wait", "recent-expired"]
    offer = rows[0]
    assert offer["session_title"] == "Beginners"
    assert offer["location"] == "Court 2"
    assert offer["student_name"] == "Asha Rao"
    assert offer["offer_expires_at"] is not None
    assert rows[1]["student_name"] == "Your child"  # no student doc: honest fallback


@pytest.mark.asyncio
async def test_a_seatless_offer_round_trips_and_is_counted(real_db) -> None:
    await _row(real_db, "acad-a", "wl-1")
    await _row(real_db, "acad-a", "wl-2")
    await _row(real_db, "acad-a", "legacy", status="offered", offer_expires_at=NOW)
    repo = MongoWaitlistRepository(real_db)

    with tenant_scope("acad-a"):
        await repo.mark_offered("wl-1", offer_expires_at=NOW, holds_seat=False)
        await repo.mark_offered("wl-2", offer_expires_at=NOW)
        seatless = await repo.get("wl-1")
        held = await repo.get("wl-2")
        legacy = await repo.get("legacy")
        count = await repo.count_seatless_offers("sess-1")
    with tenant_scope("acad-b"):
        other_tenant = await repo.count_seatless_offers("sess-1")

    assert seatless is not None and seatless.offer_holds_seat is False
    assert held is not None and held.offer_holds_seat is True
    # Rows offered before X2 have no field: they DID hold a seat.
    assert legacy is not None and legacy.offer_holds_seat is True
    assert count == 1
    assert other_tenant == 0


@pytest.mark.asyncio
async def test_count_reclaimable_matches_what_claim_longest_held_could_take(real_db) -> None:
    from backend.v2.contexts.enrollment.infrastructure.mongo_hold_repo import MongoHoldRepository

    base = {"academy_id": "acad-a", "session_id": "sess-1", "hold_seq": 1}
    await real_db["enrollments"].insert_many(
        [
            {
                **base,
                "enrollment_id": "h1",
                "student_id": "s1",
                "status": "held",
                "hold_started_at": NOW,
                "hold_reclaim_claimed_at": None,
            },
            {
                **base,
                "enrollment_id": "h2",
                "student_id": "s2",
                "status": "held",
                "hold_started_at": NOW,
                "hold_reclaim_claimed_at": NOW,
            },
            {**base, "enrollment_id": "a1", "student_id": "s3", "status": "active"},
            {
                **base,
                "academy_id": "acad-b",
                "enrollment_id": "hb",
                "student_id": "s4",
                "status": "held",
                "hold_started_at": NOW,
                "hold_reclaim_claimed_at": None,
            },
        ]
    )
    holds = MongoHoldRepository(real_db)

    with tenant_scope("acad-a"):
        assert await holds.count_reclaimable("sess-1") == 1
