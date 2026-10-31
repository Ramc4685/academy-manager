"""Migration 0211: waiver lineage keys and per-waiver version uniqueness."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

migration = importlib.import_module("backend.v2.migrations.0211_waiver_lineage_keys")


async def _seed_old_shape(db: Any) -> None:
    templates = db["waiver_templates"]
    await templates.drop_indexes()
    await templates.create_index(
        [("academy_id", 1), ("version", 1)],
        unique=True,
        name=migration.OLD_INDEX,
    )
    await templates.insert_many(
        [
            {
                "academy_id": "acad-a",
                "waiver_template_id": "a1",
                "version": "1",
                "status": "superseded",
            },
            {
                "academy_id": "acad-a",
                "waiver_template_id": "a2",
                "version": "2",
                "status": "active",
            },
            {
                "academy_id": "acad-b",
                "waiver_template_id": "b1",
                "version": "1",
                "status": "active",
            },
            {
                "academy_id": "acad-b",
                "waiver_template_id": "b2",
                "version": "2",
                "status": "draft",
                "lineage_key": "wl-keep",
            },
        ]
    )


async def _index_names(db: Any) -> set[str]:
    return {name async for name in _names(db)}


async def _names(db: Any):
    for info in (await db["waiver_templates"].index_information()).keys():
        yield info


@pytest.mark.asyncio
async def test_backfills_only_rows_without_a_key_and_swaps_the_index(real_db) -> None:
    await _seed_old_shape(real_db)

    await migration.up(real_db)

    keys = {
        doc["waiver_template_id"]: doc["lineage_key"]
        async for doc in real_db["waiver_templates"].find({})
    }
    assert keys == {"a1": "legacy", "a2": "legacy", "b1": "legacy", "b2": "wl-keep"}
    names = await _index_names(real_db)
    assert migration.NEW_INDEX in names
    assert migration.OLD_INDEX not in names


@pytest.mark.asyncio
async def test_rerun_is_a_no_op(real_db) -> None:
    await _seed_old_shape(real_db)
    await migration.up(real_db)
    before = [doc async for doc in real_db["waiver_templates"].find({}, {"_id": 0})]

    await migration.up(real_db)

    after = [doc async for doc in real_db["waiver_templates"].find({}, {"_id": 0})]
    assert sorted(before, key=lambda d: d["waiver_template_id"]) == sorted(
        after, key=lambda d: d["waiver_template_id"]
    )
    assert migration.NEW_INDEX in await _index_names(real_db)


@pytest.mark.asyncio
async def test_two_waivers_can_share_a_version_number_but_one_lineage_cannot(real_db) -> None:
    await _seed_old_shape(real_db)
    await migration.up(real_db)
    templates = real_db["waiver_templates"]

    await templates.insert_one(
        {
            "academy_id": "acad-a",
            "waiver_template_id": "photo-1",
            "version": "1",
            "lineage_key": "wl-photo",
            "status": "active",
        }
    )
    with pytest.raises(DuplicateKeyError):
        await templates.insert_one(
            {
                "academy_id": "acad-a",
                "waiver_template_id": "photo-1-dup",
                "version": "1",
                "lineage_key": "wl-photo",
                "status": "active",
            }
        )
    # Drafts have no version yet: several can exist (the old index allowed one).
    for n in range(3):
        await templates.insert_one(
            {
                "academy_id": "acad-a",
                "waiver_template_id": f"draft-{n}",
                "version": None,
                "lineage_key": f"wl-draft-{n}",
                "status": "draft",
            }
        )
