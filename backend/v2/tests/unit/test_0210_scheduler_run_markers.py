"""Migration 0210 builds the ``scheduler_run_markers`` indexes: the unique
``(academy_id, job, local_date)`` claim key led by ``academy_id`` and a 60-day
TTL on ``created_at``; no partial filter; re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0210 = importlib.import_module("backend.v2.migrations.0210_scheduler_run_markers")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0210.up(db)
    await _M0210.up(db)

    info = await db["scheduler_run_markers"].index_information()
    unique = info["scheduler_run_markers_academy_job_date_unique"]
    assert unique["key"] == [("academy_id", 1), ("job", 1), ("local_date", 1)]
    assert unique["unique"] is True
    ttl = info["scheduler_run_markers_created_ttl"]
    assert ttl["key"] == [("created_at", 1)]
    assert ttl["expireAfterSeconds"] == 60 * 24 * 60 * 60


def test_shape() -> None:
    assert _M0210.version == "0210_scheduler_run_markers"
    assert len(_M0210.INDEXES) == 2
    for _collection, _name, _keys, options in _M0210.INDEXES:
        assert "partialFilterExpression" not in options
    assert _M0210.INDEXES[0][2][0] == ("academy_id", 1)
