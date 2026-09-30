"""Migration 0212 builds the ``plan_price_changes`` indexes; re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0212 = importlib.import_module("backend.v2.migrations.0212_plan_price_changes")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0212.up(db)
    await _M0212.up(db)

    info = await db["plan_price_changes"].index_information()
    pending = info["plan_price_changes_academy_pending_plan_unique"]
    assert pending["key"] == [("academy_id", 1), ("pending_plan_id", 1)]
    assert pending["unique"] is True
    assert pending["partialFilterExpression"] == {"pending_plan_id": {"$gt": ""}}
    assert info["plan_price_changes_academy_session_status"]["key"] == [
        ("academy_id", 1),
        ("session_ids", 1),
        ("status", 1),
    ]
    assert info["plan_price_changes_academy_edit_sessions"]["key"] == [
        ("academy_id", 1),
        ("edit.session_ids", 1),
    ]


def test_every_index_leads_with_academy_id_and_never_uses_type() -> None:
    assert _M0212.version == "0212_plan_price_changes"
    for _collection, _name, keys, options in _M0212.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "$type" not in repr(options)
