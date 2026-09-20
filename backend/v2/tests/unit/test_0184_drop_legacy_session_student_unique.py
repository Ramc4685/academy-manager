"""Migration 0184 — the legacy unique (session_id, student_id) index goes away.

Production carried an auto-named ``session_id_1_student_id_1`` unique index on
``enrollments`` that no migration in this repo creates. It has no status
filter, so a ``dropped`` row blocked every later add of the same student to
the same class: the roster pre-check passed (dropped is not LIVE), the insert
hit E11000, and the admin got "a conflicting record already exists".
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0184_drop_legacy_session_student_unique")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_legacy_index(db) -> None:  # type: ignore[no-untyped-def]
    # Exactly what prod reported: default name, full (non-partial) unique.
    await db.enrollments.create_index([("session_id", 1), ("student_id", 1)], unique=True)


def _row(enrollment_id: str, status: str) -> dict[str, str]:
    return {
        "academy_id": "acad-a",
        "enrollment_id": enrollment_id,
        "session_id": "sess-1",
        "student_id": "stu-1",
        "status": status,
    }


async def test_a_dropped_row_blocks_the_readd_before_the_migration() -> None:
    """Pins the production failure so the fix is tested against the real shape."""
    db = _fresh_db()
    await _seed_legacy_index(db)
    await db.enrollments.insert_one(_row("enr-1", "dropped"))

    with pytest.raises(DuplicateKeyError):
        await db.enrollments.insert_one(_row("enr-2", "active"))


async def test_a_dropped_student_can_be_readded_after_the_migration() -> None:
    db = _fresh_db()
    await _seed_legacy_index(db)
    await db.enrollments.insert_one(_row("enr-1", "dropped"))

    await _run(db)

    await db.enrollments.insert_one(_row("enr-2", "active"))
    assert await db.enrollments.count_documents({"student_id": "stu-1"}) == 2
    assert "session_id_1_student_id_1" not in await db.enrollments.index_information()


async def test_the_index_is_matched_by_key_not_by_name() -> None:
    db = _fresh_db()
    await db.enrollments.create_index(
        [("session_id", 1), ("student_id", 1)], unique=True, name="hand_made_name"
    )

    await _run(db)

    assert "hand_made_name" not in await db.enrollments.index_information()


async def test_other_indexes_are_left_alone_and_a_rerun_is_a_noop() -> None:
    db = _fresh_db()
    await _seed_legacy_index(db)
    await db.enrollments.create_index(
        "enrollment_id", unique=True, sparse=True, name="enrollment_id_unique"
    )
    await db.enrollments.create_index(
        [("academy_id", 1), ("session_id", 1)], name="roster_by_session"
    )

    await _run(db)
    await _run(db)

    names = set(await db.enrollments.index_information())
    assert {"enrollment_id_unique", "roster_by_session"} <= names
