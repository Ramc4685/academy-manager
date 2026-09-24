"""Migration 0202 builds the family timeline lookup indexes: every one led by
``academy_id``, the parent-change ones partial on ``{field: {$gt: ""}}``
(never ``$type``, #878), none unique; re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0202 = importlib.import_module("backend.v2.migrations.0202_family_timeline_indexes")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0202.up(db)
    await _M0202.up(db)

    audit = await db["audit_logs"].index_information()
    assert audit["audit_logs_academy_entity_created"]["key"] == [
        ("academy_id", 1),
        ("entity_id", 1),
        ("created_at", -1),
    ]
    assert audit["audit_logs_academy_old_parent_created"]["partialFilterExpression"] == {
        "old_parent_id": {"$gt": ""}
    }
    assert audit["audit_logs_academy_new_parent_created"]["partialFilterExpression"] == {
        "new_parent_id": {"$gt": ""}
    }
    for collection in ("absence_notices", "pause_requests", "makeup_requests"):
        info = await db[collection].index_information()
        assert any(i["key"][:2] == [("academy_id", 1), ("student_id", 1)] for i in info.values())


def test_every_index_leads_with_academy_id() -> None:
    assert _M0202.version == "0202_family_timeline_indexes"
    assert len(_M0202.INDEXES) == 6
    for _collection, _name, keys, options in _M0202.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "unique" not in options
        partial = options.get("partialFilterExpression")
        if partial is not None:
            assert partial == {keys[1][0]: {"$gt": ""}}
            assert "$type" not in repr(partial)
