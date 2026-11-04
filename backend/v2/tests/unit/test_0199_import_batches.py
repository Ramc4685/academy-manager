"""Migration 0199 builds the import batch indexes: both led by ``academy_id``
(#849), the batch id unique per academy and not partial; re-running is a
no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0199 = importlib.import_module("backend.v2.migrations.0199_import_batches")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0199.up(db)
    await _M0199.up(db)

    info = await db["import_batches"].index_information()
    unique = info["import_batches_academy_batch_unique"]
    assert unique["key"] == [("academy_id", 1), ("import_batch_id", 1)]
    assert unique["unique"] is True
    assert "partialFilterExpression" not in unique
    assert info["import_batches_academy_created"]["key"] == [
        ("academy_id", 1),
        ("created_at", -1),
    ]


def test_every_index_leads_with_academy_id() -> None:
    assert _M0199.version == "0199_import_batches"
    assert len(_M0199.INDEXES) == 2
    for collection, _name, keys, options in _M0199.INDEXES:
        assert collection == "import_batches"
        assert keys[0] == ("academy_id", 1)
        assert "$type" not in repr(options)
