"""Contract tests for tenant-scoped session occurrence persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.domain.models import SessionOccurrence
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.migrations import run_pending_migrations
from backend.v2.shared.tenancy.context import tenant_scope


def _occurrence(occurrence_id: str, academy_id: str, session_id: str) -> SessionOccurrence:
    return SessionOccurrence(
        occurrence_id=occurrence_id,
        academy_id=academy_id,
        session_id=session_id,
        start_at=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
        end_at=datetime(2026, 6, 1, 19, 0, tzinfo=UTC),
        status="scheduled",
        scheduled_coach_id="coach-1",
    )


@pytest.mark.asyncio
async def test_occurrence_repo_isolates_tenants(db) -> None:
    await run_pending_migrations(db)

    with tenant_scope("academy-a"):
        repo = MongoSessionOccurrenceRepository(db)
        await repo.save_many([_occurrence("occ-a", "academy-a", "sess-1")])

    with tenant_scope("academy-b"):
        repo = MongoSessionOccurrenceRepository(db)
        await repo.save_many([_occurrence("occ-b", "academy-b", "sess-1")])
        rows = await repo.list_for_session_between(
            session_id="sess-1",
            start_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
            end_at=datetime(2026, 6, 1, 23, 59, tzinfo=UTC),
        )

    assert [row.occurrence_id for row in rows] == ["occ-b"]


@pytest.mark.asyncio
async def test_occurrence_repo_deduplicates_same_session_start(db) -> None:
    await run_pending_migrations(db)
    repo = MongoSessionOccurrenceRepository(db)

    with tenant_scope("academy-a"):
        first = _occurrence("occ-a", "academy-a", "sess-1")
        duplicate = first.model_copy(update={"occurrence_id": "occ-a-retry"})
        await repo.save_many([first])
        await repo.save_many([duplicate])

        rows = await repo.list_for_session_between(
            session_id="sess-1",
            start_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
            end_at=datetime(2026, 6, 1, 23, 59, tzinfo=UTC),
        )

    assert [row.occurrence_id for row in rows] == ["occ-a"]
