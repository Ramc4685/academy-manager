from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_login_attempts_migration_creates_updated_at_ttl_index(db) -> None:
    migration = importlib.import_module("backend.v2.migrations.0110_login_attempts_ttl")

    await migration.up(db)

    indexes = await db["login_attempts"].index_information()
    assert indexes["login_attempts_updated_at_ttl"]["key"] == [("updated_at", 1)]
    assert indexes["login_attempts_updated_at_ttl"]["expireAfterSeconds"] == 86400


async def test_login_attempts_migration_converts_legacy_string_updated_at(db) -> None:
    migration = importlib.import_module("backend.v2.migrations.0110_login_attempts_ttl")
    await db["login_attempts"].insert_one(
        {"identifier": "parent@example.com", "updated_at": "2099-05-29T12:00:00+00:00"}
    )

    await migration.up(db)

    doc = await db["login_attempts"].find_one({"identifier": "parent@example.com"})
    assert doc is not None
    assert not isinstance(doc["updated_at"], str)
