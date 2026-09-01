"""Migration 0162 — students uniqueness moves from global to per-academy.

The globally-unique `student_id_unique` from migration 0010 is what made the
tenant-scoped roster upsert degrade into a rejected insert (issue #610).
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0162_student_id_unique_per_academy")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_legacy_global_index(db) -> None:  # type: ignore[no-untyped-def]
    # What migration 0010's `_unique_v2_id` leaves behind.
    await db.students.create_index("student_id", unique=True, sparse=True, name="student_id_unique")


async def test_the_new_index_replaces_the_global_one() -> None:
    db = _fresh_db()
    await _seed_legacy_global_index(db)

    await _run(db)

    names = set(await db.students.index_information())
    assert "student_id_unique_per_academy" in names
    assert "student_id_unique" not in names


async def test_two_academies_may_now_share_a_student_id() -> None:
    """The exact shape that produced the production 500."""
    db = _fresh_db()
    await _seed_legacy_global_index(db)
    await db.students.insert_one({"student_id": "st-1", "academy_id": "acad-a"})

    await _run(db)

    await db.students.insert_one({"student_id": "st-1", "academy_id": "acad-b"})
    assert await db.students.count_documents({"student_id": "st-1"}) == 2


async def test_a_duplicate_pair_aborts_before_touching_any_index() -> None:
    """The pre-flight names the offenders instead of half-applying the change.

    (Such a pair cannot exist while 0010's global index stands — seeding it
    here requires leaving that index off — but a hand-repaired or restored
    collection can carry one, and that is exactly when a silent
    drop-then-fail-to-create would leave students unprotected.)
    """
    db = _fresh_db()
    await db.students.insert_many(
        [
            {"student_id": "st-9", "academy_id": "acad-a"},
            {"student_id": "st-9", "academy_id": "acad-a"},
        ]
    )

    with pytest.raises(RuntimeError, match="0162 aborted") as exc:
        await _run(db)

    assert "st-9" in str(exc.value), "the message must name the offending pair"
    assert "student_id_unique_per_academy" not in set(await db.students.index_information())


async def test_is_idempotent() -> None:
    db = _fresh_db()
    await _seed_legacy_global_index(db)

    await _run(db)
    await _run(db)

    assert "student_id_unique_per_academy" in set(await db.students.index_information())
