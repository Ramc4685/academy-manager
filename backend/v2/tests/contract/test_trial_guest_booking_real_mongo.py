"""Self-booked guest trials on a real ``mongod`` (L9 A6-1, migration 0236).

``real_db`` replays every migration, so ``trial_requests_guest_slot_unique``
is the production index. Checks, against the real repositories:

* two concurrent bookings of the last seat leave exactly one row, and the
  loser is told the date is full;
* the bookable dates subtract enrolled seats, one-time roster entries and
  seated guests, respect the guest cap and the 3h..21d window, and show the
  next three only;
* cancelling a date frees its guest seats (slot cleared) so it is open again;
* the daily ceiling and the one-per-inbox-per-class limit hold under
  concurrent bookings (unique claims, not counts), aliases included;
* another academy's isolation.

Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.application.use_cases.trial_guest_booking import (
    ACADEMY_DAILY_GUEST_CEILING,
    BookTrialGuest,
    BookTrialGuestCommand,
    ListBookableTrialDates,
    ListTrialGuests,
)
from backend.v2.contexts.enrollment.domain.public_catalog import (
    public_class_id,
    public_slot_key,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-l9-a"
B = "acad-l9-b"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


async def _seed(db: Any, academy_id: str = A, *, capacity: int = 3, enrolled: int = 0) -> None:
    now = _now()
    await db["academies"].insert_one(
        {"academy_id": academy_id, "display_name": "Club", "timezone": "America/Chicago"}
    )
    await db["sessions"].insert_one(
        {
            "academy_id": academy_id,
            "session_id": "sess-1",
            "coach_id": "coach-1",
            "title": "Juniors",
            "capacity": capacity,
            "status": "scheduled",
            "published": True,
            "days_of_week": ["Sat"],
            "start_time": "09:00",
            "end_time": "10:00",
        }
    )
    starts = [
        now + timedelta(hours=1),  # inside the 3h lead: never offered
        now + timedelta(days=1),
        now + timedelta(days=2),
        now + timedelta(days=3),
        now + timedelta(days=4),
        now + timedelta(days=30),  # past the 21-day horizon
    ]
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": academy_id,
                "occurrence_id": f"occ-{i}",
                "session_id": "sess-1",
                "start_at": start,
                "end_at": start + timedelta(hours=1),
                "status": "scheduled",
                "scheduled_coach_id": "coach-1",
            }
            for i, start in enumerate(starts)
        ]
    )
    if enrolled:
        await db["enrollments"].insert_many(
            [
                {
                    "academy_id": academy_id,
                    "enrollment_id": f"enr-{i}",
                    "session_id": "sess-1",
                    "student_id": f"stu-{i}",
                    "parent_id": "par-1",
                    "status": "active",
                }
                for i in range(enrolled)
            ]
        )


def _listing(db: Any) -> ListBookableTrialDates:
    return ListBookableTrialDates(
        sessions=MongoSessionRepository(db),
        occurrences=MongoSessionOccurrenceRepository(db),
        roster=MongoOccurrenceRosterRepository(db),
        trials=MongoTrialRequestRepository(db),
    )


def _cmd(date: Any, contact_id: str, email: str | None = None) -> BookTrialGuestCommand:
    return BookTrialGuestCommand(
        academy_id=A,
        date=date,
        contact_id=contact_id,
        email=email or f"{contact_id}@example.test",
        guest_name="Jamie Testparent",
        guest_age="9",
    )


@pytest.mark.asyncio
async def test_bookable_dates_are_the_next_three_inside_the_window(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(A):
        dates = await _listing(real_db).execute(A, guest_cap=2)

    [(public_id, shown)] = dates.items()
    assert public_id == public_class_id(A, "sess-1")
    assert [d.occurrence_id for d in shown] == ["occ-1", "occ-2", "occ-3"]
    assert [d.slot_key for d in shown] == [public_slot_key(A, f"occ-{i}") for i in (1, 2, 3)]
    assert all(d.max_slot == 2 for d in shown)


@pytest.mark.asyncio
async def test_concurrent_bookings_of_the_last_seat_leave_one_row(real_db: Any) -> None:
    # Capacity 3 with 2 enrolled: one free seat on every date.
    await _seed(real_db, capacity=3, enrolled=2)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        [first, *_] = (await _listing(real_db).execute(A, guest_cap=2))[
            public_class_id(A, "sess-1")
        ]
        assert first.max_slot == 1
        book = BookTrialGuest(trials=trials)
        results = await asyncio.gather(
            *[book.execute(_cmd(first, f"contact-{i}")) for i in range(4)]
        )

    booked = [r.booking for r in results if r.booking is not None]
    assert len(booked) == 1
    assert {r.refused for r in results if r.booking is None} == {"full"}
    rows = await real_db["trial_requests"].find({"assigned_occurrence_id": "occ-1"}).to_list(None)
    assert len(rows) == 1
    assert rows[0]["academy_id"] == A
    assert rows[0]["status"] == "approved"
    assert rows[0]["guest_slot"] == 1
    assert rows[0]["parent_user_id"] is None

    with tenant_scope(A):
        again = await _listing(real_db).execute(A, guest_cap=2)
        guests = await ListTrialGuests(trials=trials).execute("occ-1")
    # The full date is no longer offered; the next one moves up.
    assert [d.occurrence_id for d in again[public_class_id(A, "sess-1")]] == [
        "occ-2",
        "occ-3",
        "occ-4",
    ]
    assert [(g.guest_name, g.guest_age) for g in guests] == [("Jamie Testparent", "9")]


@pytest.mark.asyncio
async def test_cancelled_date_frees_the_guest_seat(real_db: Any) -> None:
    await _seed(real_db, capacity=3, enrolled=2)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        [first, *_] = (await _listing(real_db).execute(A, guest_cap=2))[
            public_class_id(A, "sess-1")
        ]
        assert (await BookTrialGuest(trials=trials).execute(_cmd(first, "contact-1"))).booking
        [reopened] = await trials.reopen_for_assigned_occurrence("occ-1")
        counts = await trials.guest_counts_for_occurrences(["occ-1"])
        book_again = await BookTrialGuest(trials=trials).execute(_cmd(first, "contact-2"))

    assert reopened.contact_id == "contact-1"
    row = await real_db["trial_requests"].find_one({"contact_id": "contact-1"})
    assert row["status"] == "pending"
    assert "guest_slot" not in row
    assert counts == {}
    assert book_again.booking is not None
    assert book_again.booking.guest_slot == 1


@pytest.mark.asyncio
async def test_a_mailbox_books_one_date_per_class(real_db: Any) -> None:
    await _seed(real_db)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        first, second, _ = (await _listing(real_db).execute(A, guest_cap=2))[
            public_class_id(A, "sess-1")
        ]
        book = BookTrialGuest(trials=trials)
        ok = await book.execute(_cmd(first, "contact-1", "jamie@example.test"))
        # Same inbox under a +alias, a second contact row: still one per class.
        refused = await book.execute(_cmd(second, "contact-2", "Jamie+trial@Example.test"))

    assert ok.booking is not None
    assert refused.booking is None
    assert refused.refused == "mailbox_limit"


@pytest.mark.asyncio
async def test_another_academy_sees_no_dates_and_cannot_count_these_guests(real_db: Any) -> None:
    await _seed(real_db)
    await _seed(real_db, B)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        [first, *_] = (await _listing(real_db).execute(A, guest_cap=2))[
            public_class_id(A, "sess-1")
        ]
        assert (await BookTrialGuest(trials=trials).execute(_cmd(first, "contact-1"))).booking

    with tenant_scope(B):
        b_dates = await _listing(real_db).execute(B, guest_cap=2)
        b_counts = await trials.guest_counts_for_occurrences(["occ-1"])
        b_guests = await ListTrialGuests(trials=trials).execute("occ-1")
        # A's key is not a key of B's page.
        assert await _listing(real_db).find(B, first.slot_key, guest_cap=2) is None

    assert b_counts == {}
    assert b_guests == []
    assert b_dates[public_class_id(B, "sess-1")][0].slot_key == public_slot_key(B, "occ-1")


@pytest.mark.asyncio
async def test_concurrent_bookings_stop_at_the_daily_ceiling(real_db: Any) -> None:
    # Three dates x five guests = 15 seats, more than the ceiling of 10.
    await _seed(real_db, capacity=20)
    trials = MongoTrialRequestRepository(real_db)
    with tenant_scope(A):
        dates = (await _listing(real_db).execute(A, guest_cap=5))[public_class_id(A, "sess-1")]
        book = BookTrialGuest(trials=trials)
        results = await asyncio.gather(
            *[book.execute(_cmd(dates[i % 3], f"contact-{i}")) for i in range(30)]
        )

    booked = [r.booking for r in results if r.booking is not None]
    assert len(booked) == ACADEMY_DAILY_GUEST_CEILING
    assert {r.refused for r in results if r.booking is None} <= {"academy_ceiling", "full"}
    assert "academy_ceiling" in {r.refused for r in results}
    assert await real_db["trial_requests"].count_documents({"academy_id": A}) == 10


@pytest.mark.asyncio
async def test_concurrent_bookings_by_one_inbox_take_one_seat_per_class(real_db: Any) -> None:
    await _seed(real_db, capacity=20)
    trials = MongoTrialRequestRepository(real_db)
    aliases = ["jamie@example.test", "JAMIE@example.test", "jamie+a@example.test"]
    with tenant_scope(A):
        dates = (await _listing(real_db).execute(A, guest_cap=5))[public_class_id(A, "sess-1")]
        book = BookTrialGuest(trials=trials)
        results = await asyncio.gather(
            *[book.execute(_cmd(dates[i % 3], f"contact-{i}", aliases[i % 3])) for i in range(9)]
        )

    assert len([r for r in results if r.booking is not None]) == 1
    assert {r.refused for r in results if r.booking is None} == {"mailbox_limit"}
    assert await real_db["trial_requests"].count_documents({"academy_id": A}) == 1
