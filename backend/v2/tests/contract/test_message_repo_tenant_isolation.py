"""Tenant-isolation tests for the shared comms message store (ADR-0006).

UIM13 added the coach/parent read + mark-read surface over this repository,
so both the read (``for_recipient``) and the write (``mark_read``) need the
per-ADR guarantee: an operation under one ``academy_id`` must not see or
touch documents that exist only under another.

#614 added a second scope inside the tenant: a session announcement is
visible only to viewers whose ``visible_session_ids`` contain its
``scope_id``. The tests at the bottom of this module pin both halves of that
— the new restriction, and the ABSENCE of any restriction on the legacy
academy-wide announcements, which must keep reaching everyone.
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
        rows = await repo.for_recipient("user-1", visible_session_ids=[])
    assert [m.message_id for m in rows] == ["a-m1"]

    with tenant_scope("academy-b"):
        rows = await repo.for_recipient("user-1", visible_session_ids=[])
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
        rows = await repo.for_recipient("user-1", visible_session_ids=[])

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
        await repo.mark_read("shared-id", "user-1", visible_session_ids=[])

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
        await repo.mark_read("other-dm", "user-1", visible_session_ids=[])
        await repo.mark_read("announcement", "user-1", visible_session_ids=[])

    other = await db["messages"].find_one({"message_id": "other-dm"})
    announcement = await db["messages"].find_one({"message_id": "announcement"})
    assert other["read_by"] == []
    assert announcement["read_by"] == ["user-1"]


@pytest.mark.asyncio
async def test_mark_read_is_idempotent(db) -> None:
    await db["messages"].insert_one(_message_doc("m1", "academy-a"))
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.mark_read("m1", "user-1", visible_session_ids=[])
        await repo.mark_read("m1", "user-1", visible_session_ids=[])

    doc = await db["messages"].find_one({"message_id": "m1"})
    assert doc["read_by"] == ["user-1"]


@pytest.mark.asyncio
async def test_legacy_announcements_stay_visible_to_everyone(db) -> None:
    """No regression for academy-wide announcements, with no data migration.

    Both shapes that exist in production today — ``scope_type`` missing
    entirely (pre-broadcast-scope docs) and ``scope_type: "academy"`` — must
    still reach a viewer with NO visible sessions at all.
    """
    await db["messages"].insert_many(
        [
            _message_doc("legacy", "academy-a", kind="announcement", recipient_id=None),
            _message_doc(
                "academy-wide",
                "academy-a",
                kind="announcement",
                recipient_id=None,
                scope_type="academy",
            ),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        rows = await repo.for_recipient("user-1", visible_session_ids=[])

    assert sorted(m.message_id for m in rows) == ["academy-wide", "legacy"]


@pytest.mark.asyncio
async def test_session_announcement_is_invisible_without_the_session(db) -> None:
    """THE #614 LEAK REGRESSION, at the repository level.

    Before the fix the predicate was ``{"kind": "announcement"}`` with no
    per-recipient clause, so this document would have been returned to every
    user in the academy.
    """
    await db["messages"].insert_many(
        [
            _message_doc(
                "sess-ann",
                "academy-a",
                kind="announcement",
                recipient_id=None,
                scope_type="session",
                scope_id="sess-1",
            ),
        ]
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        outsider = await repo.for_recipient("user-1", visible_session_ids=[])
        other_class = await repo.for_recipient("user-1", visible_session_ids=["sess-2"])
        enrolled = await repo.for_recipient("user-1", visible_session_ids=["sess-1"])

    assert outsider == []
    assert other_class == []
    assert [m.message_id for m in enrolled] == ["sess-ann"]


@pytest.mark.asyncio
async def test_mark_read_cannot_stamp_an_unseen_session_announcement(db) -> None:
    """The second leak surface: a forged read receipt on someone else's class."""
    await db["messages"].insert_one(
        _message_doc(
            "sess-ann",
            "academy-a",
            kind="announcement",
            recipient_id=None,
            scope_type="session",
            scope_id="sess-1",
        )
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.mark_read("sess-ann", "outsider", visible_session_ids=[])
        await repo.mark_read("sess-ann", "enrolled", visible_session_ids=["sess-1"])

    doc = await db["messages"].find_one({"message_id": "sess-ann"})
    assert doc["read_by"] == ["enrolled"]


@pytest.mark.asyncio
async def test_soft_deleted_messages_are_invisible_to_everyone(db) -> None:
    await db["messages"].insert_one(
        _message_doc("gone", "academy-a", kind="announcement", recipient_id=None)
    )
    repo = MongoMessageRepository(db)

    with tenant_scope("academy-a"):
        await repo.soft_delete("gone", "adm")
        assert await repo.for_recipient("user-1", visible_session_ids=[]) == []
        assert await repo.for_admin("adm") == []
        assert await repo.get("gone") is None
