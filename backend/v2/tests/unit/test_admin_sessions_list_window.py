"""Admin sessions list: academy-local day window and the all-classes view (L2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-l2"


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        yield mongomock_motor.AsyncMongoMockClient()["test_db"]
    finally:
        get_settings.cache_clear()


def _use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
    )


def _session(session_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "academy_id": ACADEMY,
        "session_id": session_id,
        "title": session_id,
        "coach_id": "coach-1",
        "capacity": 10,
        "status": "scheduled",
        **fields,
    }


@pytest.mark.asyncio
async def test_a_date_means_the_academy_local_day_not_the_utc_day(mongo_db) -> None:
    """A 7 PM Chicago class on Jan 2 is 01:00 UTC on Jan 3: it belongs to Jan 2."""
    await mongo_db["academies"].insert_one({"academy_id": ACADEMY, "timezone": "America/Chicago"})
    await mongo_db["sessions"].insert_one(
        _session(
            "evening",
            start_at=datetime(2026, 1, 3, 1, 0, tzinfo=UTC),
            end_at=datetime(2026, 1, 3, 2, 0, tzinfo=UTC),
        )
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        jan2 = await uc.list_admin_sessions(date(2026, 1, 2))
        jan3 = await uc.list_admin_sessions(date(2026, 1, 3))

    assert [r["session_id"] for r in jan2] == ["evening"]
    assert jan3 == []


@pytest.mark.asyncio
async def test_all_window_lists_far_future_and_ended_classes_with_a_phase(mongo_db) -> None:
    """L2 A0-6: a class starting in 60 days used to vanish from the list."""
    today = datetime.now(UTC).date()
    await mongo_db["academies"].insert_one({"academy_id": ACADEMY, "timezone": "America/Chicago"})

    def weekly(hour: int) -> dict[str, Any]:
        # Distinct times keep the rows easy to tell apart in the assertions.
        return {
            "days_of_week": ["Mon", "Wed"],
            "start_time": f"{hour}:00",
            "end_time": f"{hour}:45",
        }

    await mongo_db["sessions"].insert_many(
        [
            _session(
                "next-term",
                start_date=(today + timedelta(days=60)).isoformat(),
                end_date=(today + timedelta(days=150)).isoformat(),
                **weekly(15),
            ),
            _session(
                "last-term",
                start_date=(today - timedelta(days=200)).isoformat(),
                end_date=(today - timedelta(days=100)).isoformat(),
                **weekly(16),
            ),
            _session(
                "this-term", start_date=(today - timedelta(days=20)).isoformat(), **weekly(17)
            ),
            _session("gone", status="cancelled", **weekly(18)),
        ]
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        upcoming = await uc.list_admin_sessions(None, window="upcoming")
        everything = await uc.list_admin_sessions(None, window="all")

    assert "next-term" not in {r["session_id"] for r in upcoming}
    phases = {r["session_id"]: r["phase"] for r in everything}
    assert phases == {"next-term": "upcoming", "last-term": "ended", "this-term": "active"}


_SLOT = {"days_of_week": ["Tue"], "start_time": "17:00", "end_time": "18:00", "location": "Court 1"}


@pytest.mark.asyncio
async def test_an_ended_class_never_shadows_this_terms_class_in_the_same_slot(mongo_db) -> None:
    """Risk review B1: the series signature has no term, so last term's class in
    the same slot collapsed with this term's and could win, hiding its waitlist."""
    today = datetime.now(UTC).date()
    await mongo_db["academies"].insert_one({"academy_id": ACADEMY, "timezone": "America/Chicago"})
    await mongo_db["sessions"].insert_many(
        [
            _session(
                "last-term",
                start_date=(today - timedelta(days=200)).isoformat(),
                end_date=(today - timedelta(days=100)).isoformat(),
                **_SLOT,
            ),
            _session("this-term", start_date=(today - timedelta(days=20)).isoformat(), **_SLOT),
            _session(
                "next-term",
                start_date=(today + timedelta(days=60)).isoformat(),
                end_date=(today + timedelta(days=150)).isoformat(),
                **_SLOT,
            ),
        ]
    )
    await mongo_db["waitlist"].insert_one(
        {"academy_id": ACADEMY, "session_id": "next-term", "student_id": "s1", "status": "waiting"}
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        everything = await uc.list_admin_sessions(None, window="all")
        open_rows = await uc.list_admin_sessions(None, window="open")

    assert {r["session_id"]: r["phase"] for r in everything} == {
        "last-term": "ended",
        "this-term": "active",
        "next-term": "upcoming",
    }
    # The waitlist and its badge read "open": no ended class, next term's queue kept.
    assert {r["session_id"]: r["waitlist_count"] for r in open_rows} == {
        "this-term": 0,
        "next-term": 1,
    }


@pytest.mark.asyncio
async def test_all_window_lists_one_off_workshops_in_the_same_slot(mongo_db) -> None:
    """Main review: two Saturday 9:00 workshops, same coach and place, are two classes."""
    shared = {"location": "Court 1", "coach_id": "coach-1"}
    await mongo_db["sessions"].insert_many(
        [
            _session(
                "workshop-a",
                start_at=datetime(2026, 1, 3, 15, 0, tzinfo=UTC),
                end_at=datetime(2026, 1, 3, 16, 0, tzinfo=UTC),
                **shared,
            ),
            _session(
                "workshop-b",
                start_at=datetime(2026, 1, 10, 15, 0, tzinfo=UTC),
                end_at=datetime(2026, 1, 10, 16, 0, tzinfo=UTC),
                **shared,
            ),
        ]
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        rows = await uc.list_admin_sessions(None, window="all")

    assert sorted(r["session_id"] for r in rows) == ["workshop-a", "workshop-b"]


@pytest.mark.asyncio
async def test_all_window_skips_a_dated_class_without_instants(mongo_db) -> None:
    """Risk review N1: a dated class with no start_at made window=all a 500."""
    await mongo_db["sessions"].insert_many(
        [
            _session("broken"),
            _session(
                "ok",
                start_at=datetime(2026, 1, 3, 1, 0, tzinfo=UTC),
                end_at=datetime(2026, 1, 3, 2, 0, tzinfo=UTC),
            ),
        ]
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        rows = await uc.list_admin_sessions(None, window="all")

    assert [r["session_id"] for r in rows] == ["ok"]


@pytest.mark.asyncio
async def test_roster_rows_carry_their_latest_lifecycle_event(mongo_db) -> None:
    """L2 A0-12: the roster fired one history request per row to show this."""
    await mongo_db["students"].insert_many(
        [
            {"academy_id": ACADEMY, "student_id": sid, "full_name": sid, "parent_id": "p1"}
            for sid in ("s1", "s2")
        ]
    )
    now = datetime.now(UTC)
    await mongo_db["enrollments"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "enrollment_id": f"e-{sid}",
                "session_id": "c1",
                "student_id": sid,
                "parent_id": "p1",
                "status": "active",
                "created_at": now,
            }
            for sid in ("s1", "s2")
        ]
    )
    await mongo_db["enrollment_events"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "event_id": "a",
                "enrollment_id": "e-s1",
                "event_type": "enrolled",
                "occurred_at": now - timedelta(days=9),
                "effective_at": "2026-01-02",
            },
            {
                "academy_id": ACADEMY,
                "event_id": "b",
                "enrollment_id": "e-s1",
                "event_type": "resumed",
                "occurred_at": now,
                "effective_at": "2026-02-10",
            },
            # Another academy's event on the same id must not leak in.
            {
                "academy_id": "other",
                "event_id": "c",
                "enrollment_id": "e-s1",
                "event_type": "paused",
                "occurred_at": now + timedelta(days=1),
                "effective_at": "2026-03-01",
            },
        ]
    )
    uc = _use_cases(mongo_db)

    with tenant_scope(ACADEMY):
        rows = await uc.list_admin_enrollments_for_session("c1")

    by_id = {r["enrollment_id"]: r for r in rows}
    assert (by_id["e-s1"]["latest_event_type"], by_id["e-s1"]["latest_event_date"]) == (
        "resumed",
        "2026-02-10",
    )
    assert (by_id["e-s2"]["latest_event_type"], by_id["e-s2"]["latest_event_date"]) == (None, None)
