"""Contract tests for issue #783 — a schedule edit must not orphan dependents.

``maintain_session_occurrences`` re-derives every ``occurrence_id`` from the
session's weekday/time signature, so changing ``days_of_week`` re-mints the
whole set and hard-deletes the old rows that are still considered "clean".
Cleanliness only ever asked about attendance, coach attendance and payout
lines — so an approved make-up, a submitted absence notice, an assigned
trial, a roster entry or coach feedback pointing at the deleted occurrence
became a dangling reference with no cleanup and no notification.

These run the REAL composition closure the admin edit route runs, against
mongomock via the injected-db fixture (same pattern as
``test_recancel_half_cancelled_sessions.py``). They never touch a real
database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import backend.v2.composition.admin as admin_composition
from backend.v2.contexts.enrollment.domain.models import Session

# Frozen at a fixed, real Monday so this suite's outcome never depends on
# the day or time it happens to run (#872): `maintain_session_occurrences`
# and its helpers read the wall clock live, and on the schedule's own
# weekday, at or after its 09:00 start, today's occurrence is already
# "started" and the #589/#593 rule leaves it untouched — which used to flip
# 8 assertions in this file depending on when the suite ran. 2026-01-05
# 12:00 UTC is 06:00 America/Chicago (standard time, no DST in January):
# before the session's 09:00 start, so every "future Monday" assertion below
# exercises the not-yet-started path on any real-world date.
NOW = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


class _FrozenClock(datetime):
    """A ``datetime`` subclass whose ``.now()`` always returns a fixed instant.

    Monkeypatched onto ``backend.v2.composition.admin.datetime`` — the same
    technique ``test_admin_sessions.py`` uses — because
    ``maintain_session_occurrences`` and the helpers it calls
    (``_series_occurrence_candidates``, ``_is_unsettled_future_occurrence``,
    etc.) all read ``datetime.now(UTC)`` off that module's imported name.
    freezegun is not a dependency here, so this file uses no new one.
    """

    _frozen: datetime = NOW

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._frozen.replace(tzinfo=None)
        return cls._frozen.astimezone(tz)


def _freeze(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    frozen = type("_FrozenClock", (_FrozenClock,), {"_frozen": instant})
    monkeypatch.setattr(admin_composition, "datetime", frozen)


@pytest.fixture(autouse=True)
def _frozen_admin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file sees the fixed Monday 06:00 Chicago instant
    above by default — before the 09:00 class starts — so
    ``maintain_session_occurrences`` always treats today's occurrence as
    not-yet-started, regardless of the real date this suite runs on.
    """
    _freeze(monkeypatch, NOW)


def _session(days: list[str]) -> Session:
    return Session(
        session_id="sess-783",
        academy_id="test-academy",
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=NOW,
        end_at=NOW + timedelta(hours=1),
        capacity=8,
        status="scheduled",
        days_of_week=days,
        start_time="09:00",
        end_time="10:00",
        timezone="America/Chicago",
    )


def _cascade(db):
    """The production ``maintain_session_occurrences`` closure."""
    from backend.v2.composition.admin import compose_admin
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
    from backend.v2.shared.events import MongoOutbox
    from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore

    admin = compose_admin(db, MongoOutbox(db), MongoIdempotencyStore(db), FakeStripeGateway())
    assert admin.maintain_session_occurrences is not None
    return admin.maintain_session_occurrences


async def _occurrence_ids(db) -> set[str]:
    return {
        str(doc["occurrence_id"])
        async for doc in db["session_occurrences"].find({"academy_id": "test-academy"})
    }


async def _future_occurrence_ids(db) -> set[str]:
    """Occurrences the cascade may still touch: ``start_at`` from the frozen
    ``NOW`` on. Compares against the same fixed instant the production code
    sees (via ``_frozen_admin_clock``) rather than the real wall clock, so
    the result is deterministic regardless of when this suite actually runs
    (#872). ``NOW`` sits before today's 09:00 Chicago start, so today's own
    occurrence still counts as "future" here, matching the cascade's own
    not-yet-started view of it.
    """
    return {
        str(doc["occurrence_id"])
        async for doc in db["session_occurrences"].find(
            {"academy_id": "test-academy", "start_at": {"$gte": NOW}}
        )
    }


#: Every collection that pins an ``occurrence_id``, with the field it pins it
#: in. ``makeup_requests`` and ``trial_requests`` do not spell the field
#: ``occurrence_id`` — which is exactly why the original check missed them.
DEPENDENTS: list[tuple[str, str]] = [
    ("occurrence_roster_entries", "occurrence_id"),
    ("absence_notices", "occurrence_id"),
    ("session_feedback", "occurrence_id"),
    ("makeup_requests", "missed_occurrence_id"),
    ("makeup_requests", "requested_target_occurrence_id"),
    ("makeup_requests", "approved_target_occurrence_id"),
    ("trial_requests", "assigned_occurrence_id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("collection", "field"), DEPENDENTS)
async def test_schedule_edit_never_deletes_an_occurrence_with_a_live_dependent(
    db, acad, collection: str, field: str
) -> None:
    maintain = _cascade(db)

    await maintain(_session(["Mon"]))
    monday_ids = await _future_occurrence_ids(db)
    assert monday_ids, "the fixture must materialise at least one future Monday occurrence"
    pinned = sorted(monday_ids)[0]

    await db[collection].insert_one(
        {
            "academy_id": "test-academy",
            field: pinned,
            "student_id": "stu-1",
            "status": "approved",
        }
    )

    # The admin moves the class from Monday to Tuesday. Every occurrence_id
    # is re-minted, so every Monday row is now "no longer a candidate".
    await maintain(_session(["Tue"]))

    surviving = await _occurrence_ids(db)
    assert pinned in surviving, (
        f"occurrence {pinned} was deleted while {collection}.{field} still points at it"
    )
    # The dependent row itself is untouched and still resolvable.
    doc = await db[collection].find_one({"academy_id": "test-academy", field: pinned})
    assert doc is not None
    # ...and the new Tuesday schedule was still materialised.
    assert surviving - monday_ids

    # Kept, but NOT left live: a row that survives deletion only because
    # something depends on it must stop advertising itself as a class, or the
    # session runs on both the old and the new weekday forever.
    kept = await db["session_occurrences"].find_one(
        {"academy_id": "test-academy", "occurrence_id": pinned}
    )
    assert kept is not None
    assert kept["status"] == "cancelled"
    assert kept["cancellation_reason"] == "schedule_changed"


@pytest.mark.asyncio
async def test_schedule_edit_leaves_past_occurrences_alone(db, acad) -> None:
    """History is never rewritten: a past class stays exactly as it was."""
    maintain = _cascade(db)

    await maintain(_session(["Mon"]))
    past_id = "occ-783-past"
    await db["session_occurrences"].insert_one(
        {
            "academy_id": "test-academy",
            "occurrence_id": past_id,
            "session_id": "sess-783",
            "template_session_id": "sess-783",
            "start_at": NOW - timedelta(days=7),
            "end_at": NOW - timedelta(days=7) + timedelta(hours=1),
            "status": "scheduled",
        }
    )

    await maintain(_session(["Tue"]))

    past = await db["session_occurrences"].find_one(
        {"academy_id": "test-academy", "occurrence_id": past_id}
    )
    assert past is not None
    assert past["status"] == "scheduled"
    assert "cancellation_reason" not in past


@pytest.mark.asyncio
async def test_schedule_edit_still_clears_occurrences_nobody_depends_on(db, acad) -> None:
    """The guard is narrow: an untouched future occurrence is still re-keyed."""
    maintain = _cascade(db)

    await maintain(_session(["Mon"]))
    monday_ids = await _future_occurrence_ids(db)
    assert monday_ids

    await maintain(_session(["Tue"]))

    surviving = await _occurrence_ids(db)
    assert not (surviving & monday_ids)
    assert surviving


@pytest.mark.asyncio
async def test_schedule_edit_keeps_todays_started_class_but_rekeys_later_weeks(
    db, acad, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the exact edge case #869/#872 are about, instead of leaving it
    accidental: once today's own class has started, a schedule edit must
    never touch it (#589/#593) — but a LATER Monday, which has not started,
    is still re-keyed/cleared like any other future occurrence in the
    series.
    """
    maintain = _cascade(db)
    today_id = "sess-783:2026-01-05:09:00"
    next_monday_id = "sess-783:2026-01-12:09:00"

    # 06:00 Chicago: before today's class starts. Materialise the Monday
    # series, including today's own occurrence.
    _freeze(monkeypatch, NOW)
    await maintain(_session(["Mon"]))
    materialised = await _occurrence_ids(db)
    assert {today_id, next_monday_id} <= materialised
    today_before = await db["session_occurrences"].find_one(
        {"academy_id": "test-academy", "occurrence_id": today_id}
    )
    assert today_before is not None
    assert today_before["status"] == "scheduled"

    # The admin edits the schedule to Tuesday at 10:00 Chicago (16:00
    # UTC) — AFTER today's 09:00 class has already started.
    _freeze(monkeypatch, NOW + timedelta(hours=4))
    await maintain(_session(["Tue"]))

    surviving = await _occurrence_ids(db)

    # Today's class already started: the #589/#593 rule means the edit
    # never reaches it at all. Same status, same occurrence_id, still
    # resolvable — not soft-cancelled, not deleted.
    today_after = await db["session_occurrences"].find_one(
        {"academy_id": "test-academy", "occurrence_id": today_id}
    )
    assert today_after is not None
    assert today_after["status"] == "scheduled"
    assert "cancellation_reason" not in today_after
    assert today_id in surviving

    # Next Monday has NOT started yet and nothing depends on it, so it is
    # still cleared like any other clean future occurrence (matching
    # test_schedule_edit_still_clears_occurrences_nobody_depends_on).
    assert next_monday_id not in surviving

    # ...and the new Tuesday schedule was still materialised.
    assert surviving - {today_id}
