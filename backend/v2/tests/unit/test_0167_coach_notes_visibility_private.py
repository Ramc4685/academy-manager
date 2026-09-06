"""Migration 0167 — every pre-flag coach note becomes ``private``.

Notes default to private; applying that to history means parents stop
seeing old progress notes until a coach shares them again.
"""

from __future__ import annotations

import importlib

import mongomock_motor


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    mod = importlib.import_module("backend.v2.migrations.0167_coach_notes_visibility_private")
    await mod.up(db)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed(db) -> None:  # type: ignore[no-untyped-def]
    await db.progress_notes.insert_many(
        [
            {"academy_id": "acad", "note_id": "pn-legacy", "body": "old"},
            {"academy_id": "acad", "note_id": "pn-shared", "body": "new", "visibility": "shared"},
            {"academy_id": "acad", "note_id": "pn-private", "visibility": "private"},
        ]
    )
    await db.coach_skill_notes.insert_many(
        [
            {"academy_id": "acad", "note_id": "sn-legacy", "body": "old"},
            {"academy_id": "acad", "note_id": "sn-shared", "visibility": "shared"},
        ]
    )


async def _visibility(db, collection: str, note_id: str) -> str | None:  # type: ignore[no-untyped-def]
    doc = await db[collection].find_one({"note_id": note_id})
    assert doc is not None
    return doc.get("visibility")


async def test_legacy_notes_become_private_in_both_collections() -> None:
    db = _fresh_db()
    await _seed(db)

    await _run(db)

    assert await _visibility(db, "progress_notes", "pn-legacy") == "private"
    assert await _visibility(db, "coach_skill_notes", "sn-legacy") == "private"


async def test_notes_that_already_carry_a_value_are_untouched() -> None:
    db = _fresh_db()
    await _seed(db)

    await _run(db)

    assert await _visibility(db, "progress_notes", "pn-shared") == "shared"
    assert await _visibility(db, "progress_notes", "pn-private") == "private"
    assert await _visibility(db, "coach_skill_notes", "sn-shared") == "shared"


async def test_second_run_is_a_no_op() -> None:
    db = _fresh_db()
    await _seed(db)
    await _run(db)
    before = [d async for d in db.progress_notes.find({}).sort("note_id", 1)]
    before += [d async for d in db.coach_skill_notes.find({}).sort("note_id", 1)]

    await _run(db)

    after = [d async for d in db.progress_notes.find({}).sort("note_id", 1)]
    after += [d async for d in db.coach_skill_notes.find({}).sort("note_id", 1)]
    assert after == before
    assert await db.progress_notes.count_documents({"visibility": {"$exists": False}}) == 0
    assert await db.coach_skill_notes.count_documents({"visibility": {"$exists": False}}) == 0


async def test_runs_cleanly_on_empty_collections() -> None:
    db = _fresh_db()
    await _run(db)
    assert await db.progress_notes.count_documents({}) == 0


def test_version_matches_filename_stem() -> None:
    mod = importlib.import_module("backend.v2.migrations.0167_coach_notes_visibility_private")
    assert mod.version == "0167_coach_notes_visibility_private"
