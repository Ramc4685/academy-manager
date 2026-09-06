"""Audit item 7: ``event_audit`` must keep the financial event trail for 400 days."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0166_event_audit_ttl_400_days"
FOUR_HUNDRED_DAYS = 400 * 24 * 60 * 60


@pytest.fixture
def migration():
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    return importlib.import_module(MODULE_NAME)


@pytest.fixture
def original():
    return importlib.import_module("backend.v2.migrations.0002_outbox_events")


@pytest.mark.asyncio
async def test_creates_the_ttl_index_when_missing(db, migration) -> None:
    await migration.up(db)

    indexes = await db["event_audit"].index_information()
    assert indexes["completed_at_ttl"]["key"] == [("completed_at", 1)]
    assert indexes["completed_at_ttl"]["expireAfterSeconds"] == FOUR_HUNDRED_DAYS


@pytest.mark.asyncio
async def test_extends_the_90_day_index_from_0002(db, migration, original) -> None:
    await original.up(db)
    assert (await db["event_audit"].index_information())["completed_at_ttl"][
        "expireAfterSeconds"
    ] == 90 * 24 * 60 * 60

    await migration.up(db)

    indexes = await db["event_audit"].index_information()
    assert indexes["completed_at_ttl"]["key"] == [("completed_at", 1)]
    assert indexes["completed_at_ttl"]["expireAfterSeconds"] == FOUR_HUNDRED_DAYS
    # The timeline index from 0002 is untouched.
    assert "per_tenant_event_timeline" in indexes


@pytest.mark.asyncio
async def test_uses_collmod_rather_than_rebuilding_the_index(migration) -> None:
    audit = MagicMock()
    audit.index_information = AsyncMock(
        return_value={
            "completed_at_ttl": {
                "key": [("completed_at", 1)],
                "expireAfterSeconds": 90 * 24 * 60 * 60,
            }
        }
    )
    audit.create_index = AsyncMock()
    audit.drop_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=audit)
    db.command = AsyncMock(return_value={"ok": 1})

    await migration.up(db)

    db.command.assert_awaited_once_with(
        {
            "collMod": "event_audit",
            "index": {"name": "completed_at_ttl", "expireAfterSeconds": FOUR_HUNDRED_DAYS},
        }
    )
    audit.drop_index.assert_not_awaited()
    audit.create_index.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_a_no_op_when_already_400_days(migration) -> None:
    audit = MagicMock()
    audit.index_information = AsyncMock(
        return_value={
            "completed_at_ttl": {
                "key": [("completed_at", 1)],
                "expireAfterSeconds": FOUR_HUNDRED_DAYS,
            }
        }
    )
    audit.create_index = AsyncMock()
    audit.drop_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=audit)
    db.command = AsyncMock()

    await migration.up(db)

    db.command.assert_not_awaited()
    audit.create_index.assert_not_awaited()
    audit.drop_index.assert_not_awaited()
