"""Migration 0193 indexes ``users.user_id`` and ``users.auth_uid`` (People CRM spec §1).

mongomock pins SHAPE only; that ``resolve_parent_aliases``' lookups are served
is asked of a real ``mongod`` in ``contract/test_partial_index_planner_usability.py``.
"""

from __future__ import annotations

import importlib

import mongomock_motor

_M0193 = importlib.import_module("backend.v2.migrations.0193_users_parent_alias_lookup_indexes")


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def test_builds_both_indexes_and_rerun_is_a_no_op() -> None:
    db = _fresh_db()
    await _M0193.up(db)
    await _M0193.up(db)
    info = await db["users"].index_information()
    assert info["users_user_id_lookup"]["key"] == [("user_id", 1)]
    assert info["users_auth_uid_lookup"]["key"] == [("auth_uid", 1)]
    for name in ("users_user_id_lookup", "users_auth_uid_lookup"):
        assert not info[name].get("unique")
        assert "partialFilterExpression" not in info[name]


async def test_an_equivalent_index_under_another_name_is_left_alone() -> None:
    """Drift safety: same keys under a new name would raise IndexOptionsConflict."""
    db = _fresh_db()
    await db["users"].create_index([("user_id", 1)], name="user_id_1")
    await _M0193.up(db)
    info = await db["users"].index_information()
    assert "user_id_1" in info
    assert "users_user_id_lookup" not in info
    assert "users_auth_uid_lookup" in info


def test_version_and_no_type_filters() -> None:
    assert _M0193.version == "0193_users_parent_alias_lookup_indexes"
    for _name, _keys, options in _M0193.INDEXES:
        assert "$type" not in str(options)
