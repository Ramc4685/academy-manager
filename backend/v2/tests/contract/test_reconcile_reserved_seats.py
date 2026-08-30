"""Contract tests for the reserved_seats reconciliation script (issue #523).

Pre-PR-#500 parent self-cancels left ``sessions.reserved_seats``
over-counted with no ``EnrollmentCancelled`` emitted. The script
recomputes the counter from actual active enrollment counts and runs the
production ``PromoteFromWaitlist`` path for sessions that regain
capacity. These tests exercise the injected-db entrypoint the same way
``test_backfill_p4_legacy_payments.py`` does.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts.reconcile_reserved_seats import (
    reconcile_reserved_seats,
    session_delta_row,
)
from backend.v2.shared.ids import new_ulid

ACADEMY = "test-academy"


def _session_doc(
    session_id: str,
    *,
    reserved_seats: int,
    capacity: int = 2,
    status: str = "scheduled",
) -> dict:
    return {
        "session_id": session_id,
        "academy_id": ACADEMY,
        "coach_id": "coach-1",
        "title": "Junior A",
        "location": "Court 1",
        "start_at": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        "end_at": datetime(2026, 9, 1, 10, 30, tzinfo=UTC),
        "capacity": capacity,
        "reserved_seats": reserved_seats,
        "status": status,
    }


def _enrollment_doc(session_id: str, student_id: str, status: str = "active") -> dict:
    return {
        "enrollment_id": str(new_ulid()),
        "academy_id": ACADEMY,
        "session_id": session_id,
        "student_id": student_id,
        "status": status,
    }


def _waitlist_doc(session_id: str, student_id: str, joined_at: datetime) -> dict:
    return {
        "waitlist_id": str(new_ulid()),
        "academy_id": ACADEMY,
        "session_id": session_id,
        "student_id": student_id,
        "parent_id": f"parent-of-{student_id}",
        "joined_at": joined_at,
        "status": "waiting",
    }


def test_session_delta_row_counts_missing_reserved_seats_as_zero() -> None:
    row = session_delta_row(
        {"session_id": "s1", "capacity": 3, "title": "A", "status": "scheduled"},
        active_count=2,
    )
    assert row["reserved_seats"] == 0
    assert row["delta"] == -2


@pytest.mark.asyncio
async def test_dry_run_reports_delta_without_writing_or_promoting(db) -> None:
    session_id = str(new_ulid())
    # Pre-fix self-cancel: enrollment cancelled, seat never released.
    await db["sessions"].insert_one(_session_doc(session_id, reserved_seats=2, capacity=2))
    await db["enrollments"].insert_one(_enrollment_doc(session_id, "st-active"))
    await db["enrollments"].insert_one(_enrollment_doc(session_id, "st-gone", status="cancelled"))
    await db["waitlist"].insert_one(
        _waitlist_doc(session_id, "st-waiting", datetime(2026, 8, 1, tzinfo=UTC))
    )

    result = await reconcile_reserved_seats(db, academy_id=ACADEMY, dry_run=True)

    assert [r["session_id"] for r in result["drifted"]] == [session_id]
    assert result["drifted"][0]["delta"] == 1
    assert result["corrected"] == 0
    assert result["promotions"] == {}

    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 2
    entry = await db["waitlist"].find_one({"session_id": session_id})
    assert entry["status"] == "waiting"


@pytest.mark.asyncio
async def test_apply_corrects_counter_and_promotes_fifo_until_full(db) -> None:
    session_id = str(new_ulid())
    # Capacity 2, one real active enrollment, counter stuck at 2: one
    # phantom seat. Two waiting entries — only the older one fits.
    await db["sessions"].insert_one(_session_doc(session_id, reserved_seats=2, capacity=2))
    await db["enrollments"].insert_one(_enrollment_doc(session_id, "st-active"))
    await db["waitlist"].insert_one(
        _waitlist_doc(session_id, "st-older", datetime(2026, 8, 1, 8, 0, tzinfo=UTC))
    )
    await db["waitlist"].insert_one(
        _waitlist_doc(session_id, "st-newer", datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    )

    result = await reconcile_reserved_seats(db, academy_id=ACADEMY, dry_run=False)

    assert result["corrected"] == 1
    assert result["cas_lost"] == []
    assert result["promotions"] == {session_id: 1}

    session = await db["sessions"].find_one({"session_id": session_id})
    # Corrected to 1, then promotion re-reserved the freed seat.
    assert session["reserved_seats"] == 2

    older = await db["waitlist"].find_one({"student_id": "st-older"})
    newer = await db["waitlist"].find_one({"student_id": "st-newer"})
    assert older["status"] == "promoted"
    assert newer["status"] == "waiting"

    promoted = await db["enrollments"].find_one(
        {"session_id": session_id, "student_id": "st-older"}
    )
    assert promoted is not None
    assert promoted["status"] == "active"

    events = [doc async for doc in db["outbox_events"].find({})]
    assert any(e["name"] == "Enrollment.WaitlistPromoted" for e in events)


@pytest.mark.asyncio
async def test_consistent_sessions_and_other_academies_left_untouched(db) -> None:
    ok_session = str(new_ulid())
    await db["sessions"].insert_one(_session_doc(ok_session, reserved_seats=1))
    await db["enrollments"].insert_one(_enrollment_doc(ok_session, "st-1"))

    foreign_session = str(new_ulid())
    foreign = _session_doc(foreign_session, reserved_seats=5)
    foreign["academy_id"] = "other-academy"
    await db["sessions"].insert_one(foreign)

    result = await reconcile_reserved_seats(db, academy_id=ACADEMY, dry_run=False)

    assert result["inspected"] == 1
    assert result["drifted"] == []
    assert result["corrected"] == 0

    untouched = await db["sessions"].find_one({"session_id": foreign_session})
    assert untouched["reserved_seats"] == 5


@pytest.mark.asyncio
async def test_promotion_runs_even_when_counter_already_consistent(db) -> None:
    """A consistent counter with free capacity and a waiting entry still
    promotes — the pre-fix drift may have been hand-corrected while the
    waitlist stayed stuck."""
    session_id = str(new_ulid())
    await db["sessions"].insert_one(_session_doc(session_id, reserved_seats=0, capacity=1))
    await db["waitlist"].insert_one(
        _waitlist_doc(session_id, "st-waiting", datetime(2026, 8, 1, tzinfo=UTC))
    )

    result = await reconcile_reserved_seats(db, academy_id=ACADEMY, dry_run=False)

    assert result["drifted"] == []
    assert result["promotions"] == {session_id: 1}
    entry = await db["waitlist"].find_one({"session_id": session_id})
    assert entry["status"] == "promoted"
    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 1


@pytest.mark.asyncio
async def test_skip_promotion_only_fixes_counters(db) -> None:
    session_id = str(new_ulid())
    await db["sessions"].insert_one(_session_doc(session_id, reserved_seats=1, capacity=1))
    await db["waitlist"].insert_one(
        _waitlist_doc(session_id, "st-waiting", datetime(2026, 8, 1, tzinfo=UTC))
    )

    result = await reconcile_reserved_seats(
        db, academy_id=ACADEMY, dry_run=False, skip_promotion=True
    )

    assert result["corrected"] == 1
    assert result["promotions"] == {}
    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 0
    entry = await db["waitlist"].find_one({"session_id": session_id})
    assert entry["status"] == "waiting"
