"""Contract tests for `MongoSessionRepository.assigned_session_ids_for_coach`.

Coach announcement visibility (#614) must agree with the authorization the
announcement route uses (`coach_id` on the session, no date filter). The
window query `for_coach` cannot serve that: a recurring series stores a single
`start_at` stamped when it was created, so a Tue/Thu class that has been
running for months is permanently "in the past" and would silently drop out of
the coach's inbox while they can still post to it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

# `db` fixture is provided by contract/conftest.py (mongomock-motor in-process)


def _doc(session_id: str, academy_id: str, coach_id: str, start_at: datetime) -> dict:
    return {
        "session_id": session_id,
        "academy_id": academy_id,
        "coach_id": coach_id,
        "title": "Beginner Badminton",
        "location": "Court 1",
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
        "capacity": 12,
        "status": "scheduled",
    }


@pytest.mark.asyncio
async def test_a_series_that_started_in_the_past_is_still_assigned(db):
    now = datetime.now(UTC)
    await db["sessions"].insert_many(
        [
            _doc("sess-old", "academy-A", "coach-1", now - timedelta(days=60)),
            _doc("sess-new", "academy-A", "coach-1", now + timedelta(days=1)),
        ]
    )
    repo = MongoSessionRepository(db)

    with tenant_scope("academy-A"):
        assigned = await repo.assigned_session_ids_for_coach("coach-1")
        upcoming = {s.session_id for s in await repo.for_coach("coach-1")}

    assert assigned == ["sess-new", "sess-old"]
    # The window query is what made the announcement invisible.
    assert upcoming == {"sess-new"}


@pytest.mark.asyncio
async def test_another_coach_and_another_tenant_are_excluded(db):
    now = datetime.now(UTC)
    await db["sessions"].insert_many(
        [
            _doc("sess-a", "academy-A", "coach-1", now - timedelta(days=5)),
            _doc("sess-other-coach", "academy-A", "coach-2", now - timedelta(days=5)),
            _doc("sess-other-tenant", "academy-B", "coach-1", now - timedelta(days=5)),
        ]
    )
    repo = MongoSessionRepository(db)

    with tenant_scope("academy-A"):
        assert await repo.assigned_session_ids_for_coach("coach-1") == ["sess-a"]
