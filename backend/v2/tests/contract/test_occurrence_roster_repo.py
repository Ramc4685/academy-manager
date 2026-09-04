"""Mongo contract tests for one-time occurrence roster entries (issue #651)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _occurrence(
    academy_id: str, occurrence_id: str, session_id: str, start_at: datetime, **extra: object
) -> dict[str, object]:
    return {
        "academy_id": academy_id,
        "occurrence_id": occurrence_id,
        "session_id": session_id,
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
        "status": "scheduled",
        "scheduled_coach_id": "coach-1",
        **extra,
    }


def _entry(
    academy_id: str, entry_id: str, occurrence_id: str, student_id: str
) -> OccurrenceRosterEntry:
    return OccurrenceRosterEntry(
        entry_id=entry_id,
        academy_id=academy_id,
        occurrence_id=occurrence_id,
        student_id=student_id,
        source="makeup",
        origin_request_id=f"req-{entry_id}",
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_remove_future_for_student_deletes_only_future_rows_of_that_session(db) -> None:
    """Issue #651: leaving a session clears the student's future make-up /
    trial rows for it, keeps past rows (attendance history), rows for other
    students, rows in other sessions, and rows in other tenants."""
    await db["session_occurrences"].insert_many(
        [
            _occurrence("academy-a", "occ-past", "sess-1", NOW - timedelta(days=1)),
            _occurrence("academy-a", "occ-boundary", "sess-1", NOW),
            _occurrence("academy-a", "occ-future", "sess-1", NOW + timedelta(days=1)),
            # Derived from the same recurring session template.
            _occurrence(
                "academy-a",
                "occ-derived",
                "occ-derived",
                NOW + timedelta(days=8),
                template_session_id="sess-1",
            ),
            _occurrence("academy-a", "occ-other-session", "sess-2", NOW + timedelta(days=1)),
            _occurrence("academy-b", "occ-future", "sess-1", NOW + timedelta(days=1)),
        ]
    )
    repo = MongoOccurrenceRosterRepository(db)
    with tenant_scope("academy-a"):
        for entry_id, occurrence_id, student_id in (
            ("a-past", "occ-past", "st-1"),
            ("a-boundary", "occ-boundary", "st-1"),
            ("a-future", "occ-future", "st-1"),
            ("a-derived", "occ-derived", "st-1"),
            ("a-other-session", "occ-other-session", "st-1"),
            ("a-other-student", "occ-future", "st-2"),
        ):
            await repo.add(_entry("academy-a", entry_id, occurrence_id, student_id))
    with tenant_scope("academy-b"):
        await repo.add(_entry("academy-b", "b-future", "occ-future", "st-1"))

    with tenant_scope("academy-a"):
        deleted = await repo.remove_future_for_student(
            session_id="sess-1", student_id="st-1", after=NOW
        )

    assert deleted == 2
    remaining = sorted([doc["entry_id"] async for doc in db["occurrence_roster_entries"].find({})])
    assert remaining == [
        "a-boundary",
        "a-other-session",
        "a-other-student",
        "a-past",
        "b-future",
    ]


@pytest.mark.asyncio
async def test_remove_future_for_student_returns_zero_when_nothing_matches(db) -> None:
    repo = MongoOccurrenceRosterRepository(db)
    with tenant_scope("academy-a"):
        await repo.add(_entry("academy-a", "a-1", "occ-unknown", "st-1"))
        deleted = await repo.remove_future_for_student(
            session_id="sess-1", student_id="st-1", after=NOW
        )
    assert deleted == 0
    assert await db["occurrence_roster_entries"].count_documents({}) == 1
