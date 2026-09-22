"""Migration 0188 — the per-academy id indexes move from ``$type`` to ``$gt: ""``.

A ``$type: "string"`` partial index enforces uniqueness but the planner never
uses it for an equality lookup, so 0162/0186 silently took the id index away
from every by-id read (#849). mongomock evaluates neither partial filters nor
query plans, so what is pinned here is the SHAPE and the create-before-drop
swap; planner use was verified with ``explain()`` against a real MongoDB.
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError

_MODULE = "backend.v2.migrations.0188_per_academy_id_indexes_planner_usable"


def _targets() -> list[tuple[str, str, str, str]]:
    return list(importlib.import_module(_MODULE).TARGETS)


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    await importlib.import_module(_MODULE).up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_type_filtered_indexes(db) -> None:  # type: ignore[no-untyped-def]
    # What migrations 0150 / 0162 / 0186 leave behind.
    for collection, field, old_index, _new in _targets():
        await db[collection].create_index(
            [("academy_id", 1), (field, 1)],
            unique=True,
            partialFilterExpression={field: {"$type": "string"}},
            name=old_index,
        )


def test_it_covers_every_index_0150_0162_and_0186_built() -> None:
    built_by_0186 = importlib.import_module(
        "backend.v2.migrations.0186_enrollment_core_ids_unique_per_academy"
    ).TARGETS
    expected_old = {t[3] for t in built_by_0186} | {
        "student_id_unique_per_academy",
        "student_user_id_unique_per_academy",
    }
    assert {t[2] for t in _targets()} == expected_old


async def test_each_index_is_rebuilt_with_the_planner_usable_filter() -> None:
    db = _fresh_db()
    await _seed_type_filtered_indexes(db)

    await _run(db)

    for collection, field, old_index, new_index in _targets():
        info = await db[collection].index_information()
        assert old_index not in info
        assert info[new_index]["key"] == [("academy_id", 1), (field, 1)]
        assert info[new_index]["unique"] is True
        assert info[new_index]["partialFilterExpression"] == {field: {"$gt": ""}}


async def test_uniqueness_is_still_per_academy() -> None:
    db = _fresh_db()
    await _seed_type_filtered_indexes(db)
    await db.enrollments.insert_one({"enrollment_id": "enr-1", "academy_id": "acad-a"})

    await _run(db)

    await db.enrollments.insert_one({"enrollment_id": "enr-1", "academy_id": "acad-b"})
    with pytest.raises(DuplicateKeyError):
        await db.enrollments.insert_one({"enrollment_id": "enr-1", "academy_id": "acad-a"})


async def test_it_is_idempotent_and_safe_when_the_old_index_is_absent() -> None:
    db = _fresh_db()

    await _run(db)
    await _run(db)

    for collection, _field, old_index, new_index in _targets():
        names = set(await db[collection].index_information())
        assert new_index in names
        assert old_index not in names
