"""Migration 0191 — the stopgap ``digest_id`` lookup indexes from 0189 are dropped (#880).

mongomock pins index SHAPE only; that the scoped ``(academy_id, digest_id)``
update is served by the per-academy unique index is asked of a real
``mongod`` in ``contract/test_partial_index_planner_usability.py``.
"""

from __future__ import annotations

import importlib

import mongomock_motor

_M0189 = importlib.import_module("backend.v2.migrations.0189_remaining_ids_unique_per_academy")
_M0191 = importlib.import_module("backend.v2.migrations.0191_drop_digest_send_id_lookup_indexes")


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


def test_targets_are_exactly_the_0189_plain_lookups() -> None:
    assert {c: names[0] for c, names in _M0191.TARGETS.items()} == {
        c: name for c, (_field, name) in _M0189.PLAIN_LOOKUPS.items()
    }
    assert {(c, names[1]) for c, names in _M0191.TARGETS.items()} <= {
        (t[0], t[3]) for t in _M0189.TARGETS
    }


async def test_drops_the_stopgap_and_keeps_the_per_academy_unique_index() -> None:
    db = _fresh_db()
    await _M0189.up(db)
    for collection, (stopgap, per_academy) in _M0191.TARGETS.items():
        info = await db[collection].index_information()
        assert stopgap in info and per_academy in info

    await _M0191.up(db)

    for collection, (stopgap, per_academy) in _M0191.TARGETS.items():
        info = await db[collection].index_information()
        assert stopgap not in info
        assert info[per_academy]["key"] == [("academy_id", 1), ("digest_id", 1)]
        assert info[per_academy]["unique"] is True


async def test_rerun_and_absent_index_are_no_ops() -> None:
    db = _fresh_db()
    await _M0189.up(db)

    await _M0191.up(db)
    await _M0191.up(db)  # second run: stopgap already gone

    for collection, (stopgap, per_academy) in _M0191.TARGETS.items():
        info = await db[collection].index_information()
        assert stopgap not in info
        assert per_academy in info


async def test_keeps_the_stopgap_when_0189_has_not_run() -> None:
    """Without the per-academy index there is nothing to fall back on."""
    db = _fresh_db()
    for collection, (stopgap, _per_academy) in _M0191.TARGETS.items():
        await db[collection].create_index("digest_id", name=stopgap)

    await _M0191.up(db)

    for collection, (stopgap, _per_academy) in _M0191.TARGETS.items():
        assert stopgap in await db[collection].index_information()
