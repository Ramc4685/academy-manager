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

from backend.v2.contexts.enrollment.domain.models import Session

NOW = datetime.now(UTC)


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
    monday_ids = await _occurrence_ids(db)
    assert monday_ids, "the fixture must materialise at least one Monday occurrence"
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


@pytest.mark.asyncio
async def test_schedule_edit_still_clears_occurrences_nobody_depends_on(db, acad) -> None:
    """The guard is narrow: an untouched future occurrence is still re-keyed."""
    maintain = _cascade(db)

    await maintain(_session(["Mon"]))
    monday_ids = await _occurrence_ids(db)
    assert monday_ids

    await maintain(_session(["Tue"]))

    surviving = await _occurrence_ids(db)
    assert not (surviving & monday_ids)
    assert surviving
