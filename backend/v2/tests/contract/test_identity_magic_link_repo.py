"""Contract tests for MongoMagicLinkRepository.

Verifies:
- Round-trip insert / get_by_hash.
- ``get_by_hash`` is NOT academy-scoped — it resolves by hash alone and returns
  the stored ``academy_id`` so the use case can enforce tenant binding itself.
- Two tokens for different tenants coexist and stay distinct.
- ``mark_used`` is atomic + single-use (second claim returns False).
- Naive datetimes read back from Mongo are coerced to aware UTC.
- Migration 0149 creates the unique + TTL indexes.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.domain.models import MagicLinkRecord
from backend.v2.contexts.identity.infrastructure.mongo_magic_link_repo import (
    MongoMagicLinkRepository,
)


def _record(**overrides: object) -> MagicLinkRecord:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "magic_link_id": "ml-1",
        "token_hash": "hash-1",
        "user_id": "parent-1",
        "academy_id": "acad-a",
        "next_path": "/parent/payments",
        "created_at": now,
        "expires_at": now + timedelta(hours=72),
        "purge_at": now + timedelta(hours=72) + timedelta(days=7),
        "used_at": None,
    }
    defaults.update(overrides)
    return MagicLinkRecord(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_insert_and_get_by_hash_round_trip(db) -> None:
    repo = MongoMagicLinkRepository(db)
    await repo.insert(_record(token_hash="h-abc", academy_id="acad-a"))

    got = await repo.get_by_hash("h-abc")

    assert got is not None
    assert got.token_hash == "h-abc"
    assert got.academy_id == "acad-a"
    assert got.user_id == "parent-1"
    assert got.next_path == "/parent/payments"
    assert got.used_at is None


@pytest.mark.asyncio
async def test_get_by_hash_returns_none_for_unknown_hash(db) -> None:
    repo = MongoMagicLinkRepository(db)
    assert await repo.get_by_hash("missing") is None


@pytest.mark.asyncio
async def test_get_by_hash_is_not_academy_scoped(db) -> None:
    """Two tenants' tokens coexist; each resolves by hash with its academy intact.

    The repo deliberately does not filter by tenant — the ConsumeMagicLink use
    case compares the returned ``academy_id`` to the resolved tenant. This test
    pins that the academy is faithfully returned for both.
    """
    repo = MongoMagicLinkRepository(db)
    await repo.insert(_record(token_hash="h-a", academy_id="acad-a", user_id="p-a"))
    await repo.insert(_record(token_hash="h-b", academy_id="acad-b", user_id="p-b"))

    got_a = await repo.get_by_hash("h-a")
    got_b = await repo.get_by_hash("h-b")

    assert got_a is not None and got_a.academy_id == "acad-a" and got_a.user_id == "p-a"
    assert got_b is not None and got_b.academy_id == "acad-b" and got_b.user_id == "p-b"


@pytest.mark.asyncio
async def test_mark_used_is_atomic_and_single_use(db) -> None:
    repo = MongoMagicLinkRepository(db)
    await repo.insert(_record(token_hash="h-once"))
    now = datetime.now(UTC)

    first = await repo.mark_used("h-once", used_at=now)
    second = await repo.mark_used("h-once", used_at=now)

    assert first is True
    assert second is False  # already consumed
    got = await repo.get_by_hash("h-once")
    assert got is not None and got.used_at is not None


@pytest.mark.asyncio
async def test_mark_used_returns_false_for_unknown_hash(db) -> None:
    repo = MongoMagicLinkRepository(db)
    assert await repo.mark_used("missing", used_at=datetime.now(UTC)) is False


@pytest.mark.asyncio
async def test_naive_datetimes_are_coerced_to_utc(db) -> None:
    # Simulate a driver that stored naive datetimes by writing the raw doc.
    naive = datetime(2026, 7, 23, 12, 0, 0)
    await db["parent_magic_links"].insert_one(
        {
            "magic_link_id": "ml-naive",
            "token_hash": "h-naive",
            "user_id": "parent-1",
            "academy_id": "acad-a",
            "next_path": "/parent/dashboard",
            "created_at": naive,
            "expires_at": naive,
            "purge_at": naive,
            "used_at": None,
        }
    )
    repo = MongoMagicLinkRepository(db)

    got = await repo.get_by_hash("h-naive")

    assert got is not None
    assert got.expires_at.tzinfo is not None
    assert got.expires_at.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_migration_creates_indexes(db) -> None:
    migration = importlib.import_module("backend.v2.migrations.0149_parent_magic_link_indexes")
    await migration.up(db)

    indexes = {idx["name"]: idx async for idx in db["parent_magic_links"].list_indexes()}

    assert "parent_magic_links_token_hash_unique" in indexes
    assert indexes["parent_magic_links_token_hash_unique"].get("unique") is True
    assert "parent_magic_links_purge_at_ttl" in indexes
    assert indexes["parent_magic_links_purge_at_ttl"].get("expireAfterSeconds") == 0
