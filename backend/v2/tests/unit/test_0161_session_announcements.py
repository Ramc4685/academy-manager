"""Migration 0161 — index for the #614 session-scoped announcement reads."""

from __future__ import annotations

import importlib

import mongomock_motor


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0161_session_announcements")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


def test_version_matches_the_filename_stem() -> None:
    mod = importlib.import_module("backend.v2.migrations.0161_session_announcements")
    assert mod.version == "0161_session_announcements"


async def test_creates_the_session_announcement_timeline_index() -> None:
    db = _fresh_db()

    await _run(db)

    info = await db.messages.index_information()
    assert "session_announcement_timeline" in info
    keys = [tuple(k) for k in info["session_announcement_timeline"]["key"]]
    assert keys == [
        ("academy_id", 1),
        ("scope_type", 1),
        ("scope_id", 1),
        ("created_at", -1),
    ]


async def test_is_rerunnable() -> None:
    db = _fresh_db()

    await _run(db)
    await _run(db)

    assert "session_announcement_timeline" in await db.messages.index_information()
