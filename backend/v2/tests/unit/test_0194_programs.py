"""Migration 0194 builds the ``programs`` indexes and the published-class
lookup on ``sessions``, all led by ``academy_id``, none partial or global."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0194 = importlib.import_module("backend.v2.migrations.0194_programs")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0194.up(db)
    await _M0194.up(db)

    programs = await db["programs"].index_information()
    assert set(programs) == {"_id_", "programs_academy_program_unique", "programs_academy_sort"}
    unique = programs["programs_academy_program_unique"]
    assert unique["key"] == [("academy_id", 1), ("program_id", 1)]
    assert unique["unique"] is True
    assert programs["programs_academy_sort"]["key"] == [("academy_id", 1), ("sort_order", 1)]
    assert not programs["programs_academy_sort"].get("unique")

    sessions = await db["sessions"].index_information()
    published = sessions["sessions_academy_published"]
    assert published["key"] == [("academy_id", 1), ("published", 1)]
    assert not published.get("unique")


def test_every_index_leads_with_academy_id_and_has_no_partial_filter() -> None:
    assert _M0194.version == "0194_programs"
    for _collection, _name, keys, options in _M0194.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "partialFilterExpression" not in options
