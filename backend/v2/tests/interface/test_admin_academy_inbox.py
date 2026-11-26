"""The academy inbox on the admin side (D-18, S61).

A parent's message to the academy lands in admin Messages under that family,
every admin and owner sees the whole thread, and staff replies to a parent join
it. Private DMs (admin to coach, admin to admin) stay private.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.v2.shared.comms import CommsService, Message
from backend.v2.tests.interface.conftest import _build_admin_use_cases, _claims, _make_admin_app


@dataclass
class _StubInbox:
    """Mirrors composition/academy_inbox.AcademyInbox: parents get a thread."""

    parents: frozenset[str] = frozenset({"p-1"})

    async def thread_for(self, academy_id: str, recipient_id: str) -> str | None:
        return recipient_id if recipient_id in self.parents else None

    async def staff_name(self, user_id: str) -> str | None:
        return {"u-admin": "Marcus (front desk)"}.get(user_id)


@contextmanager
def _admin(seed, role: str) -> Iterator[TestClient]:
    app = _make_admin_app(_claims(role), _build_admin_use_cases(seed))
    app.state.academy_inbox = _StubInbox()
    with TestClient(app) as client:
        yield client


async def _parent_writes(seed, body: str = "Sam will be 10 minutes late on Saturday.") -> Message:
    comms = CommsService(messages=seed["messages"], academy_id="acad")
    return await comms.send_to_academy(parent_id="p-1", body=body)


def _messages(client) -> dict[str, dict]:
    r = client.get("/api/v2/admin/messages")
    assert r.status_code == 200, r.text
    return {m["message_id"]: m for m in r.json()["messages"]}


async def test_parent_message_lands_under_the_family_for_every_admin(admin_seed):
    m = await _parent_writes(admin_seed)

    for role in ("admin", "admin-only"):
        with _admin(admin_seed, role) as client:
            row = _messages(client)[m.message_id]
        assert row["counterparty_id"] == "p-1"
        assert row["sender_id"] == "p-1"
        assert row["is_read"] is False


async def test_reply_to_a_parent_joins_the_shared_thread_with_its_author(admin_seed):
    await _parent_writes(admin_seed)
    with _admin(admin_seed, "admin") as client:
        r = client.post(
            "/api/v2/admin/messages/dm",
            json={"recipient_id": "p-1", "body": "Thanks, we'll tell the coach."},
        )
    assert r.status_code == 200, r.text
    reply_id = r.json()["message_id"]
    stored = admin_seed["messages"].rows[reply_id]
    assert stored.inbox_thread_id == "p-1"
    assert stored.author_display_name == "Marcus (front desk)"

    # The owner (another admin) sees Marcus's reply in the same thread, read.
    with _admin(admin_seed, "admin-only") as client:
        row = _messages(client)[reply_id]
    assert row["counterparty_id"] == "p-1"
    assert row["author_display_name"] == "Marcus (front desk)"
    assert row["is_read"] is True


async def test_dm_to_a_coach_stays_private_to_its_sender(admin_seed):
    with _admin(admin_seed, "admin") as client:
        r = client.post(
            "/api/v2/admin/messages/dm",
            json={"recipient_id": "u-coach", "body": "Can you cover Saturday?"},
        )
    assert r.status_code == 200, r.text
    dm_id = r.json()["message_id"]
    assert admin_seed["messages"].rows[dm_id].inbox_thread_id is None
    assert admin_seed["messages"].rows[dm_id].author_display_name is None

    with _admin(admin_seed, "admin-only") as client:
        assert dm_id not in _messages(client)


async def test_any_admin_can_mark_a_family_message_read_only_for_themselves(admin_seed):
    m = await _parent_writes(admin_seed)
    with _admin(admin_seed, "admin") as client:
        assert client.post(f"/api/v2/admin/messages/{m.message_id}/read").status_code == 200
        assert _messages(client)[m.message_id]["is_read"] is True
    with _admin(admin_seed, "admin-only") as client:
        assert _messages(client)[m.message_id]["is_read"] is False


async def test_admin_cannot_mark_another_admins_private_dm_read(admin_seed):
    admin_seed["messages"].rows["priv"] = Message(
        message_id="priv",
        academy_id="acad",
        kind="dm",
        sender_id="u-coach",
        sender_persona="coach",
        recipient_id="u-admin",
        body="Private",
        created_at=datetime(2026, 11, 26, 8, 0, tzinfo=UTC),
    )
    with _admin(admin_seed, "admin-only") as client:
        assert client.post("/api/v2/admin/messages/priv/read").status_code == 200
    assert admin_seed["messages"].rows["priv"].read_by == []
