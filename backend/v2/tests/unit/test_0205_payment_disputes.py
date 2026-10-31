"""Migration 0205 builds the ``payment_disputes`` indexes: both led by
``academy_id``, the dispute one unique, no partial filter; re-running is a
no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0205 = importlib.import_module("backend.v2.migrations.0205_payment_disputes")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0205.up(db)
    await _M0205.up(db)

    info = await db["payment_disputes"].index_information()
    assert info["payment_disputes_academy_dispute_unique"]["key"] == [
        ("academy_id", 1),
        ("dispute_id", 1),
    ]
    assert info["payment_disputes_academy_dispute_unique"]["unique"] is True
    assert info["payment_disputes_academy_open_opened"]["key"] == [
        ("academy_id", 1),
        ("is_open", 1),
        ("opened_at", -1),
    ]


def test_every_index_leads_with_academy_id() -> None:
    assert _M0205.version == "0205_payment_disputes"
    assert len(_M0205.INDEXES) == 2
    for _collection, _name, keys, options in _M0205.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "partialFilterExpression" not in options
