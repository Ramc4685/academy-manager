"""Migration 0201: one unique ``(academy_id, source_key)`` index on
``family_follow_ups``, partial on a non-empty key (never ``$type``/``$exists``,
#878); re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0201 = importlib.import_module("backend.v2.migrations.0201_crm_follow_up_source_key")


async def test_builds_the_index_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0201.up(db)
    await _M0201.up(db)

    info = await db["family_follow_ups"].index_information()
    index = info["family_follow_ups_academy_source_key_unique"]
    assert index["key"] == [("academy_id", 1), ("source_key", 1)]
    assert index["unique"] is True
    assert index["partialFilterExpression"] == {"source_key": {"$gt": ""}}


def test_leads_with_academy_id_and_filters_with_gt_empty_string() -> None:
    assert _M0201.version == "0201_crm_follow_up_source_key"
    for _collection, _name, keys, options in _M0201.INDEXES:
        assert keys[0] == ("academy_id", 1)
        partial = options["partialFilterExpression"]
        assert partial == {"source_key": {"$gt": ""}}
        assert "$type" not in str(partial) and "$exists" not in str(partial)
