"""Migration 0192 builds the ``crm_contacts`` indexes, all led by ``academy_id``.

mongomock pins index SHAPE only; that the dedupe lookup is served by its
partial index is asked of a real ``mongod`` in
``contract/test_partial_index_planner_usability.py``.
"""

from __future__ import annotations

import importlib

import mongomock_motor

from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import DEDUPE_INDEX_NAME

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = _fresh_db()
    await _M0192.up(db)
    await _M0192.up(db)

    info = await db["crm_contacts"].index_information()
    assert set(info) == {"_id_"} | {name for name, _k, _o in _M0192.INDEXES}

    contact = info["crm_contacts_academy_contact_unique"]
    assert contact["key"] == [("academy_id", 1), ("contact_id", 1)]
    assert contact["unique"] is True

    dedupe = info[DEDUPE_INDEX_NAME]
    assert dedupe["key"] == [("academy_id", 1), ("dedupe_key", 1)]
    assert dedupe["unique"] is True
    assert dedupe["partialFilterExpression"] == {"dedupe_key": {"$gt": ""}}

    assert info["crm_contacts_academy_pipeline_created"]["key"] == [
        ("academy_id", 1),
        ("pipeline_status", 1),
        ("created_at", -1),
    ]


def test_every_index_leads_with_academy_id_and_no_type_filters() -> None:
    assert _M0192.version == "0192_crm_contacts"
    for _name, keys, options in _M0192.INDEXES:
        assert keys[0] == ("academy_id", 1)
        partial = options.get("partialFilterExpression", {})
        assert "$type" not in str(partial) and "$exists" not in str(partial)
