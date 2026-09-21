"""Migration 0186 — enrollment-core id uniqueness moves from global to per-academy.

Same trap as #610 / migration 0162, on the four enrollment-core collections
(issue #849): a bare-id unique index disagrees with tenant-scoped upserts.
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError

# (collection, id field, old global index, new per-academy index)
_TARGETS = [
    ("sessions", "session_id", "session_id_unique", "session_id_unique_per_academy"),
    ("enrollments", "enrollment_id", "enrollment_id_unique", "enrollment_id_unique_per_academy"),
    (
        "session_occurrences",
        "occurrence_id",
        "session_occurrence_id_unique",
        "session_occurrence_id_unique_per_academy",
    ),
    ("attendance", "attendance_id", "attendance_id_unique", "attendance_id_unique_per_academy"),
]


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module(
        "backend.v2.migrations.0186_enrollment_core_ids_unique_per_academy"
    )
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_legacy_global_indexes(db) -> None:  # type: ignore[no-untyped-def]
    # What migrations 0010 / 0020 / 0081 leave behind.
    for collection, field, old_index, _new in _TARGETS:
        await db[collection].create_index(field, unique=True, sparse=True, name=old_index)


def test_the_targets_match_the_migration() -> None:
    mod = importlib.import_module(
        "backend.v2.migrations.0186_enrollment_core_ids_unique_per_academy"
    )
    assert [tuple(t) for t in mod.TARGETS] == _TARGETS


async def test_each_new_index_replaces_the_global_one() -> None:
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)

    await _run(db)

    for collection, field, old_index, new_index in _TARGETS:
        info = await db[collection].index_information()
        assert old_index not in info
        assert info[new_index]["key"] == [("academy_id", 1), (field, 1)]
        assert info[new_index]["unique"] is True
        assert info[new_index]["partialFilterExpression"] == {field: {"$type": "string"}}


@pytest.mark.parametrize(("collection", "field"), [(t[0], t[1]) for t in _TARGETS])
async def test_two_academies_may_now_share_an_id(collection: str, field: str) -> None:
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)
    await db[collection].insert_one({field: "x-1", "academy_id": "acad-a"})

    await _run(db)

    await db[collection].insert_one({field: "x-1", "academy_id": "acad-b"})
    assert await db[collection].count_documents({field: "x-1"}) == 2


@pytest.mark.parametrize(("collection", "field"), [(t[0], t[1]) for t in _TARGETS])
async def test_one_academy_still_cannot_reuse_an_id(collection: str, field: str) -> None:
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)
    await db[collection].insert_one({field: "x-1", "academy_id": "acad-a"})

    await _run(db)

    with pytest.raises(DuplicateKeyError):
        await db[collection].insert_one({field: "x-1", "academy_id": "acad-a"})


async def test_a_duplicate_pair_aborts_before_touching_any_index() -> None:
    """One dirty collection stops the whole batch, not just its own swap.

    (Such a pair cannot exist while the global index stands — seeding it needs
    that index left off — but a hand-repaired or restored collection can carry
    one.) The offender is the LAST target, so an abort that fired per
    collection would already have swapped the first three.
    """
    db = _fresh_db()
    for collection, field, old_index, _new in _TARGETS[:-1]:
        await db[collection].create_index(field, unique=True, sparse=True, name=old_index)
    await db.attendance.insert_many(
        [
            {"attendance_id": "att-1", "academy_id": "acad-a"},
            {"attendance_id": "att-1", "academy_id": "acad-a"},
        ]
    )

    with pytest.raises(RuntimeError, match=r"attendance.*'acad-a'/'att-1' x2"):
        await _run(db)

    for collection, _field, old_index, new_index in _TARGETS[:-1]:
        names = set(await db[collection].index_information())
        assert old_index in names
        assert new_index not in names
    assert "attendance_id_unique_per_academy" not in set(await db.attendance.index_information())


# Docs with no id staying out of the constraint is asserted on the index SHAPE
# above (``partialFilterExpression``): mongomock does not evaluate ``$type``
# partial filters, so a behavioural test here would only exercise the fake.


async def test_it_is_idempotent_and_safe_when_the_old_index_is_absent() -> None:
    db = _fresh_db()

    await _run(db)
    await _run(db)

    for collection, _field, old_index, new_index in _TARGETS:
        names = set(await db[collection].index_information())
        assert new_index in names
        assert old_index not in names
