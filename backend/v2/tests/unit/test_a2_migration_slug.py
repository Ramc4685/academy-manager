from __future__ import annotations

import importlib

import mongomock_motor


async def _run_migration(db):
    mod = importlib.import_module("backend.v2.migrations.0105_academy_slug")
    await mod.up(db)


async def test_slug_backfilled_from_id():
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test"]
    await db.academies.insert_one({"_id": "my-academy", "display_name": "My Academy"})
    await _run_migration(db)
    doc = await db.academies.find_one({"_id": "my-academy"})
    assert doc["slug"] == "my-academy"
    assert doc["academy_id"] == "my-academy"


async def test_slug_not_overwritten_if_already_set():
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test"]
    await db.academies.insert_one({"_id": "acad1", "slug": "custom-slug", "academy_id": "acad1"})
    await _run_migration(db)
    doc = await db.academies.find_one({"_id": "acad1"})
    assert doc["slug"] == "custom-slug"
    assert doc["academy_id"] == "acad1"
