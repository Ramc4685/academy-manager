"""Tenant-isolation tests for the shared comms message store (ADR-0006).

UIM13 added the coach/parent read + mark-read surface over this repository,
so both the read (``for_recipient``) and the write (``mark_read``) need the
per-ADR guarantee: an operation under one ``academy_id`` must not see or
touch documents that exist only under another.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.shared.comms import MongoMessageRepository
from backend.v2.shared.tenancy.context import tenant_scope


def _message_doc(message_id: str, academy_id: str, **overrides) -> dict:
    doc = {
        "message_id": message_id,
        "academy_id": academy_id,
        "kind": "dm",
        "sender_id": "adm",
        "sender_persona": "admin",
        "recipient_id": "user-1",
        "body": "Hello",
        "created_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "read_by": [],
    }
    doc.update(overrides)
    return doc


@pytest.mark.asyncio
async def test_for_recipient_isolates_tenants(db) -> None:
    await db["messages"].insert_many(
        [
            _message_doc("a-m1", "academy-a"),
            _message_doc("b-m1", "academy-b"),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        rows = await repo.for_recipient("user-1")
    assert [m.message_id for m in rows] == ["a-m1"]

    with tenant_scope("academy-b"):
        rows = await repo.for_recipient("user-1")
    assert [m.message_id for m in rows] == ["b-m1"]


@pytest.mark.asyncio
async def test_for_recipient_scopes_to_recipient_and_announcements(db) -> None:
    await db["messages"].insert_many(
        [
            _message_doc("own-dm", "academy-a", recipient_id="user-1"),
            _message_doc("other-dm", "academy-a", recipient_id="user-2"),
            _message_doc("announcement", "academy-a", kind="announcement", recipient_id=None),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        rows = await repo.for_recipient("user-1")

    assert sorted(m.message_id for m in rows) == ["announcement", "own-dm"]


@pytest.mark.asyncio
async def test_mark_read_isolates_tenants(db) -> None:
    """A cross-tenant message id must not be markable."""
    await db["messages"].insert_many(
        [
            _message_doc("shared-id", "academy-a"),
            _message_doc("shared-id", "academy-b"),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.mark_read("shared-id", "user-1")

    a_doc = await db["messages"].find_one({"message_id": "shared-id", "academy_id": "academy-a"})
    b_doc = await db["messages"].find_one({"message_id": "shared-id", "academy_id": "academy-b"})
    assert a_doc["read_by"] == ["user-1"]
    assert b_doc["read_by"] == []


@pytest.mark.asyncio
async def test_mark_read_is_scoped_to_the_callers_own_messages(db) -> None:
    """Another user's DM cannot be stamped with a forged read receipt."""
    await db["messages"].insert_many(
        [
            _message_doc("other-dm", "academy-a", recipient_id="user-2"),
            _message_doc("announcement", "academy-a", kind="announcement", recipient_id=None),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.mark_read("other-dm", "user-1")
        await repo.mark_read("announcement", "user-1")

    other = await db["messages"].find_one({"message_id": "other-dm"})
    announcement = await db["messages"].find_one({"message_id": "announcement"})
    assert other["read_by"] == []
    assert announcement["read_by"] == ["user-1"]


@pytest.mark.asyncio
async def test_mark_read_is_idempotent(db) -> None:
    await db["messages"].insert_one(_message_doc("m1", "academy-a"))
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.mark_read("m1", "user-1")
        await repo.mark_read("m1", "user-1")

    doc = await db["messages"].find_one({"message_id": "m1"})
    assert doc["read_by"] == ["user-1"]
