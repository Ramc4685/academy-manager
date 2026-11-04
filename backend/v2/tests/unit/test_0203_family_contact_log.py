"""Migration 0203 builds the ``family_contact_log`` indexes: both led by
``academy_id``, the id one unique, no partial filter; re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0203 = importlib.import_module("backend.v2.migrations.0203_family_contact_log")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0203.up(db)
    await _M0203.up(db)

    info = await db["family_contact_log"].index_information()
    assert info["family_contact_log_academy_log_id_unique"]["key"] == [
        ("academy_id", 1),
        ("log_id", 1),
    ]
    assert info["family_contact_log_academy_log_id_unique"]["unique"] is True
    assert info["family_contact_log_academy_parent_created"]["key"] == [
        ("academy_id", 1),
        ("parent_id", 1),
        ("created_at", -1),
    ]


def test_every_index_leads_with_academy_id() -> None:
    assert _M0203.version == "0203_family_contact_log"
    assert len(_M0203.INDEXES) == 2
    for _collection, _name, keys, options in _M0203.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "partialFilterExpression" not in options
