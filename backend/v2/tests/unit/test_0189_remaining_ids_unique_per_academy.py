"""Migration 0189 — the remaining thirty id indexes move from global to per-academy.

Issue #849, batch 3. mongomock evaluates neither partial filters nor query
plans, so what is pinned here is the index SHAPE, the all-or-nothing
pre-flight and the create-before-drop swap; planner use and absent-id
behaviour were verified with ``explain()`` against a real MongoDB.
"""

from __future__ import annotations

import importlib

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError

_MODULE = "backend.v2.migrations.0189_remaining_ids_unique_per_academy"


def _mod():  # type: ignore[no-untyped-def]
    return importlib.import_module(_MODULE)


def _targets() -> list[tuple[str, str, str, str]]:
    return list(_mod().TARGETS)


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    await _mod().up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_legacy_global_indexes(db, targets=None) -> None:  # type: ignore[no-untyped-def]
    # Uniqueness on the bare id, as migrations 0040..0148 leave behind.
    for collection, field, old_index, _new in targets or _targets():
        await db[collection].create_index(field, unique=True, sparse=True, name=old_index)


def test_there_are_thirty_targets_with_distinct_names() -> None:
    targets = _targets()
    assert len(targets) == 30
    assert len({(t[0], t[3]) for t in targets}) == 30
    assert len({(t[0], t[1]) for t in targets}) == 30


def test_the_provider_message_id_index_is_left_global() -> None:
    assert ("message_deliveries", "provider_message_id") not in {(t[0], t[1]) for t in _targets()}


def test_the_launch_readiness_audit_expects_the_new_settings_index() -> None:
    from backend.scripts import launch_readiness_audit as audit

    expected = {
        name
        for value in vars(audit).values()
        if isinstance(value, dict)
        for coll, names in value.items()
        if coll == "academy_settings" and isinstance(names, set)
        for name in names
    }
    new_name = next(t[3] for t in _targets() if t[0] == "academy_settings")
    assert new_name in expected
    assert "academy_settings_id_unique" not in expected


async def test_each_new_index_replaces_the_global_one() -> None:
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)

    await _run(db)

    for collection, field, old_index, new_index in _targets():
        info = await db[collection].index_information()
        assert old_index not in info
        assert info[new_index]["key"] == [("academy_id", 1), (field, 1)]
        assert info[new_index]["unique"] is True
        assert info[new_index]["partialFilterExpression"] == {field: {"$gt": ""}}


async def test_the_digest_collections_keep_a_plain_digest_id_index() -> None:
    """``mark_sent`` and friends update by ``digest_id`` with no ``academy_id``."""
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)

    await _run(db)

    for collection, (field, name) in _mod().PLAIN_LOOKUPS.items():
        info = await db[collection].index_information()
        assert info[name]["key"] == [(field, 1)]
        assert not info[name].get("unique")


@pytest.mark.parametrize(("collection", "field"), [(t[0], t[1]) for t in _targets()])
async def test_uniqueness_is_per_academy(collection: str, field: str) -> None:
    db = _fresh_db()
    await _seed_legacy_global_indexes(db)
    await db[collection].insert_one({field: "x-1", "academy_id": "acad-a"})

    await _run(db)

    await db[collection].insert_one({field: "x-1", "academy_id": "acad-b"})
    with pytest.raises(DuplicateKeyError):
        await db[collection].insert_one({field: "x-1", "academy_id": "acad-a"})


async def test_a_duplicate_pair_aborts_before_touching_any_index() -> None:
    """One dirty collection stops the whole batch. The offender is the LAST
    target, so a per-collection abort would already have swapped the rest."""
    db = _fresh_db()
    targets = _targets()
    await _seed_legacy_global_indexes(db, targets[:-1])
    last_collection, last_field, _old, last_new = targets[-1]
    await db[last_collection].insert_many(
        [
            {last_field: "dup-1", "academy_id": "acad-a"},
            {last_field: "dup-1", "academy_id": "acad-a"},
        ]
    )

    with pytest.raises(RuntimeError, match=rf"{last_collection}.*'acad-a'/'dup-1' x2"):
        await _run(db)

    for collection, _field, old_index, new_index in targets[:-1]:
        names = set(await db[collection].index_information())
        assert old_index in names
        assert new_index not in names
    assert last_new not in set(await db[last_collection].index_information())


async def test_it_is_idempotent_and_safe_when_the_old_index_is_absent() -> None:
    db = _fresh_db()

    await _run(db)
    await _run(db)

    for collection, _field, old_index, new_index in _targets():
        names = set(await db[collection].index_information())
        assert new_index in names
        assert old_index not in names
