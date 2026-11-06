"""Migration 0225: the ``nurture_sends`` claim index."""

from __future__ import annotations

import importlib
from pathlib import Path

import mongomock_motor
import pytest

_M = importlib.import_module("backend.v2.migrations.0225_nurture_sends")


def test_version_is_the_filename_stem() -> None:
    assert _M.version == Path(_M.__file__).stem == "0225_nurture_sends"


@pytest.mark.asyncio
async def test_builds_the_unique_partial_index_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["m0225"]
    await _M.up(db)
    await _M.up(db)
    index = (await db["nurture_sends"].index_information())["nurture_sends_key_unique"]
    assert index["key"] == [("academy_id", 1), ("subject_id", 1), ("digest_date", 1)]
    assert index["unique"] is True
    assert index["partialFilterExpression"] == {"subject_id": {"$gt": ""}}
