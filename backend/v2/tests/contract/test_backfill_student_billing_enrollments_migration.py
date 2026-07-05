"""Contract tests — migration 0145 legacy-enrollment projection backfill.

2026-07-04 incident: ``student_billing_enrollments`` was empty for legacy-flow
enrollments, so autopay setup completion failed. The migration must create the
projection insert-only ($setOnInsert), never touch existing docs, and skip
enrollments that must not be offered autopay.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

migration_0145 = importlib.import_module(
    "backend.v2.migrations.0145_backfill_student_billing_enrollments"
)

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _legacy(
    enrollment_id: str,
    *,
    status: str = "active",
    academy_id: str = "acad-1",
    parent_id: str | None = "parent-1",
    is_deleted: bool = False,
) -> dict:
    doc = {
        "enrollment_id": enrollment_id,
        "academy_id": academy_id,
        "student_id": "student-1",
        "session_id": "sess-1",
        "status": status,
        "enrolled_at": NOW,
        "is_deleted": is_deleted,
    }
    if parent_id is not None:
        doc["parent_id"] = parent_id
    return doc


@pytest.mark.asyncio
async def test_creates_projection_for_active_and_paused_enrollments(db) -> None:
    await db["enrollments"].insert_many(
        [
            _legacy("e-active"),
            _legacy("e-paused", status="paused"),
        ]
    )

    await migration_0145.up(db)

    by_id = {d["enrollment_id"]: d async for d in db["student_billing_enrollments"].find({})}
    assert set(by_id) == {"e-active", "e-paused"}
    active = by_id["e-active"]
    assert active["academy_id"] == "acad-1"
    assert active["parent_id"] == "parent-1"
    assert active["student_id"] == "student-1"
    assert active["session_type_id"] == "sess-1"
    assert active["billing_start_date"].replace(tzinfo=UTC) == NOW
    assert active["autopay_enrollment_status"] == "offered"
    assert active["status"] == "active"
    assert by_id["e-paused"]["status"] == "paused"


@pytest.mark.asyncio
async def test_skips_dead_and_deleted_enrollments(db) -> None:
    await db["enrollments"].insert_many(
        [
            _legacy("e-cancelled", status="cancelled"),
            _legacy("e-withdrawn", status="withdrawn"),
            _legacy("e-deleted", is_deleted=True),
        ]
    )

    await migration_0145.up(db)

    assert await db["student_billing_enrollments"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_never_modifies_existing_projection(db) -> None:
    """Insert-only: a projection already written by the v2 flow (or the manual
    prod backfill) keeps its autopay state and mapping."""
    await db["enrollments"].insert_one(_legacy("e-existing"))
    await db["student_billing_enrollments"].insert_one(
        {
            "enrollment_id": "e-existing",
            "academy_id": "acad-1",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "session_type_id": "type-real",
            "billing_start_date": NOW,
            "status": "active",
            "autopay_enrollment_status": "active",
            "enrolled_at": NOW,
            "updated_at": NOW,
        }
    )

    await migration_0145.up(db)

    docs = [d async for d in db["student_billing_enrollments"].find({})]
    assert len(docs) == 1
    assert docs[0]["autopay_enrollment_status"] == "active"
    assert docs[0]["session_type_id"] == "type-real"


@pytest.mark.asyncio
async def test_second_run_is_idempotent(db) -> None:
    await db["enrollments"].insert_one(_legacy("e-once"))

    await migration_0145.up(db)
    first = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-once"})
    await migration_0145.up(db)

    assert await db["student_billing_enrollments"].count_documents({}) == 1
    second = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-once"})
    assert second["updated_at"] == first["updated_at"]


@pytest.mark.asyncio
async def test_resolves_parent_from_student_doc_when_enrollment_lacks_it(db) -> None:
    await db["enrollments"].insert_one(_legacy("e-no-parent", parent_id=None))
    await db["students"].insert_one(
        {"academy_id": "acad-1", "student_id": "student-1", "parent_id": "parent-via-student"}
    )

    await migration_0145.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-no-parent"})
    assert doc is not None
    assert doc["parent_id"] == "parent-via-student"


@pytest.mark.asyncio
async def test_skips_enrollment_with_unresolvable_parent(db) -> None:
    await db["enrollments"].insert_one(_legacy("e-orphan", parent_id=None))

    await migration_0145.up(db)

    assert await db["student_billing_enrollments"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_backfills_per_academy(db) -> None:
    await db["enrollments"].insert_many(
        [
            _legacy("e-a", academy_id="acad-a"),
            _legacy("e-b", academy_id="acad-b"),
        ]
    )

    await migration_0145.up(db)

    doc_a = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-a"})
    doc_b = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-b"})
    assert doc_a["academy_id"] == "acad-a"
    assert doc_b["academy_id"] == "acad-b"
