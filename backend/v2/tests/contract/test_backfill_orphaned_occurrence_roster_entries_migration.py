"""Contract tests — migration 0180 orphaned occurrence-roster backfill
(issue #694).

A one-time (make-up/trial) roster row is orphaned once its occurrence is
gone (session delete/regenerate) or cancelled (single-date cancel or
whole-session cancel) — the coach can never mark it, so it must not
survive the migration.
"""

from __future__ import annotations

import importlib

import pytest

migration_0180 = importlib.import_module(
    "backend.v2.migrations.0180_backfill_orphaned_occurrence_roster_entries"
)

ACADEMY = "acad-694"


def _entry(entry_id: str, occurrence_id: str, academy_id: str = ACADEMY) -> dict:
    return {
        "entry_id": entry_id,
        "academy_id": academy_id,
        "occurrence_id": occurrence_id,
        "student_id": "student-1",
        "source": "makeup",
        "origin_request_id": "req-1",
    }


def _occurrence(occurrence_id: str, status: str = "scheduled", academy_id: str = ACADEMY) -> dict:
    return {"occurrence_id": occurrence_id, "academy_id": academy_id, "status": status}


async def _remaining_ids(db) -> set[str]:
    return {d["entry_id"] async for d in db["occurrence_roster_entries"].find({})}


@pytest.mark.asyncio
async def test_deletes_rows_whose_occurrence_no_longer_exists(db) -> None:
    await db["occurrence_roster_entries"].insert_many(
        [_entry("ore-live", "occ-live"), _entry("ore-gone", "occ-gone")]
    )
    await db["session_occurrences"].insert_one(_occurrence("occ-live"))

    await migration_0180.up(db)

    assert await _remaining_ids(db) == {"ore-live"}


@pytest.mark.asyncio
async def test_deletes_rows_whose_occurrence_is_cancelled(db) -> None:
    await db["occurrence_roster_entries"].insert_many(
        [_entry("ore-scheduled", "occ-a"), _entry("ore-cancelled", "occ-b")]
    )
    await db["session_occurrences"].insert_many(
        [_occurrence("occ-a", status="scheduled"), _occurrence("occ-b", status="cancelled")]
    )

    await migration_0180.up(db)

    assert await _remaining_ids(db) == {"ore-scheduled"}


@pytest.mark.asyncio
async def test_does_not_cross_tenants(db) -> None:
    """An occurrence in a DIFFERENT academy must never save an orphaned row —
    the lookup and delete are both tenant-scoped."""
    await db["occurrence_roster_entries"].insert_one(
        _entry("ore-cross-tenant", "occ-shared", academy_id="acad-a")
    )
    # Same occurrence_id exists, but scoped to a different academy.
    await db["session_occurrences"].insert_one(
        _occurrence("occ-shared", status="scheduled", academy_id="acad-b")
    )

    await migration_0180.up(db)

    assert await _remaining_ids(db) == set()


@pytest.mark.asyncio
async def test_empty_collection_is_a_no_op(db) -> None:
    await migration_0180.up(db)
    assert await _remaining_ids(db) == set()


@pytest.mark.asyncio
async def test_rerun_is_idempotent(db) -> None:
    await db["occurrence_roster_entries"].insert_many(
        [_entry("ore-live", "occ-live"), _entry("ore-gone", "occ-gone")]
    )
    await db["session_occurrences"].insert_one(_occurrence("occ-live"))

    await migration_0180.up(db)
    await migration_0180.up(db)

    assert await _remaining_ids(db) == {"ore-live"}
