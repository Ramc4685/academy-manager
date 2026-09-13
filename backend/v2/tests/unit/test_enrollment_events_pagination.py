"""#748: GET /admin/enrollments/{id}/events ran an unbounded Mongo scan and
materialised the whole history for every request, tripping the Cloudflare
Worker's CPU/memory limit for enrollments with large event histories. The
read model must page results (limit + cursor) instead of returning everything."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_list_enrollment_events,
)
from backend.v2.shared.tenancy.context import tenant_scope


def _db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    return client["test_db"]


async def _seed(db, *, enrollment_id: str, academy_id: str, count: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    docs = []
    for i in range(count):
        docs.append(
            {
                "event_id": f"evt-{i:04d}",
                "enrollment_id": enrollment_id,
                "academy_id": academy_id,
                "event_type": "note_added",
                "occurred_at": base + timedelta(minutes=i),
                "effective_at": (base + timedelta(minutes=i)).isoformat(),
                "actor_id": "admin-1",
            }
        )
    await db["enrollment_events"].insert_many(docs)


@pytest.mark.asyncio
async def test_list_enrollment_events_pages_a_large_history_with_no_gaps_or_dupes() -> None:
    db = _db()
    await _seed(db, enrollment_id="enr-1", academy_id="acad", count=1000)
    list_enrollment_events = make_list_enrollment_events(db)

    with tenant_scope("acad"):
        events, next_cursor = await list_enrollment_events("enr-1", limit=100)
        assert len(events) == 100
        assert next_cursor is not None

        all_events = list(events)
        seen_ids = {e["event_id"] for e in events}
        cursor = next_cursor
        pages = 1
        while cursor is not None:
            page, cursor = await list_enrollment_events("enr-1", limit=100, cursor=cursor)
            assert len(page) <= 100
            for e in page:
                assert e["event_id"] not in seen_ids
                seen_ids.add(e["event_id"])
            all_events.extend(page)
            pages += 1
            assert pages <= 20  # sanity bound so a bug can't loop forever

        assert len(all_events) == 1000
        assert len(seen_ids) == 1000

        # Most-recent-first: the last seeded event (evt-0999) comes back first.
        assert all_events[0]["event_id"] == "evt-0999"
        assert all_events[-1]["event_id"] == "evt-0000"

        occurred_ats = [e["event_id"] for e in all_events]
        assert occurred_ats == sorted(occurred_ats, reverse=True)


@pytest.mark.asyncio
async def test_list_enrollment_events_clamps_limit_to_500() -> None:
    db = _db()
    await _seed(db, enrollment_id="enr-2", academy_id="acad", count=600)
    list_enrollment_events = make_list_enrollment_events(db)

    with tenant_scope("acad"):
        events, next_cursor = await list_enrollment_events("enr-2", limit=10_000)
        assert len(events) == 500
        assert next_cursor is not None


@pytest.mark.asyncio
async def test_list_enrollment_events_no_more_pages_returns_none_cursor() -> None:
    db = _db()
    await _seed(db, enrollment_id="enr-3", academy_id="acad", count=5)
    list_enrollment_events = make_list_enrollment_events(db)

    with tenant_scope("acad"):
        events, next_cursor = await list_enrollment_events("enr-3", limit=100)
        assert len(events) == 5
        assert next_cursor is None


@pytest.mark.asyncio
async def test_list_enrollment_events_is_tenant_scoped() -> None:
    db = _db()
    await _seed(db, enrollment_id="enr-4", academy_id="acad-a", count=3)
    await _seed(db, enrollment_id="enr-4", academy_id="acad-b", count=7)
    list_enrollment_events = make_list_enrollment_events(db)

    with tenant_scope("acad-a"):
        events, _ = await list_enrollment_events("enr-4", limit=100)
        assert len(events) == 3
