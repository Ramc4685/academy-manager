"""Migration 0244: evening-win and report-card claim ids unique per academy (#849).

Real MongoDB (``real_db``): mongomock ignores partial filters and would not
prove two academies may share a ``digest_id``.
"""

from __future__ import annotations

import importlib

import pytest
from pymongo.errors import DuplicateKeyError

_MOD = importlib.import_module("backend.v2.migrations.0244_win_report_card_send_ids_per_academy")
_COLLECTIONS = [c for c, _old, _new in _MOD.TARGETS]


async def _seed_old_shape(db) -> None:  # type: ignore[no-untyped-def]
    # real_db has every migration replayed already; start from the pre-0244 shape.
    for collection, old_index, _new in _MOD.TARGETS:
        await db[collection].drop()
        await db[collection].create_index("digest_id", unique=True, name=old_index)


async def test_swaps_the_global_index_for_a_per_academy_one(real_db) -> None:  # type: ignore[no-untyped-def]
    await _seed_old_shape(real_db)

    await _MOD.up(real_db)
    await _MOD.up(real_db)  # idempotent

    for collection, old_index, new_index in _MOD.TARGETS:
        info = await real_db[collection].index_information()
        assert old_index not in info
        assert info[new_index]["key"] == [("academy_id", 1), ("digest_id", 1)]
        assert info[new_index]["unique"] is True
        assert info[new_index]["partialFilterExpression"] == {"digest_id": {"$gt": ""}}


@pytest.mark.parametrize("collection", _COLLECTIONS)
async def test_two_academies_may_share_a_digest_id_but_one_may_not_repeat_it(
    real_db, collection
) -> None:  # type: ignore[no-untyped-def]
    await _MOD.up(real_db)
    coll = real_db[collection]
    await coll.insert_one({"academy_id": "acad_a", "digest_id": "dg_1"})
    await coll.insert_one({"academy_id": "acad_b", "digest_id": "dg_1"})

    with pytest.raises(DuplicateKeyError):
        await coll.insert_one({"academy_id": "acad_a", "digest_id": "dg_1"})


async def test_preflight_raises_on_duplicates_and_leaves_the_old_index(real_db) -> None:  # type: ignore[no-untyped-def]
    # No unique index on parent_win_sends here so a duplicate pair can exist,
    # as on a restored or hand-patched database.
    for collection, _old, _new in _MOD.TARGETS:
        await real_db[collection].drop()
    coll = real_db["parent_win_sends"]
    await coll.insert_many(
        [
            {"academy_id": "acad_a", "digest_id": "dg_dup", "parent_id": "p1"},
            {"academy_id": "acad_a", "digest_id": "dg_dup", "parent_id": "p2"},
        ]
    )
    await real_db["parent_report_card_sends"].create_index(
        "digest_id", unique=True, name="parent_report_card_send_id_unique"
    )

    with pytest.raises(RuntimeError, match=r"0244 aborted.*parent_win_sends.*dg_dup"):
        await _MOD.up(real_db)

    # All-or-nothing: the other collection was not touched either.
    info = await real_db["parent_report_card_sends"].index_information()
    assert "parent_report_card_send_id_unique" in info
    assert "parent_report_card_send_id_per_academy_uq" not in info
    assert "parent_win_send_id_per_academy_uq" not in await coll.index_information()
