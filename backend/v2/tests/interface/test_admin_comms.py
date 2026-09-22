"""Admin comms BFF — broadcast + DM + inbox + coach digest test-send + log."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    CoachDigestTargetNotFound,
    SendCoachDigestTestResult,
)
from backend.v2.interfaces.admin import comms_routes
from backend.v2.shared.comms import Message
from backend.v2.shared.config.settings import get_settings


def test_broadcast_creates_announcement(admin_client):
    r = admin_client.post(
        "/api/v2/admin/messages/broadcast",
        json={"body": "Tournament this Saturday!"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "announcement"
    assert body["recipient_id"] is None
    assert "Tournament" in body["body"]


def test_broadcast_rejects_a_session_scope(admin_client):
    """A session-typed broadcast would be an announcement visible to NOBODY.

    ``scope_type`` is a free-form string on this legacy endpoint, so
    ``"session"`` has always been storable. Since #614 a session-scoped
    announcement is matched by ``scope_id``, and a broadcast has none — the
    document would pass the write and then fail every read. Rejecting it at the
    boundary turns a silently-swallowed academy announcement into a 422.
    """
    r = admin_client.post(
        "/api/v2/admin/messages/broadcast",
        json={"body": "Tournament", "scope_type": "session"},
    )
    assert r.status_code == 422, r.text

    listed = admin_client.get("/api/v2/admin/messages")
    assert all("Tournament" not in m["body"] for m in listed.json()["messages"])


def test_dm_creates_targeted_message(admin_client):
    r = admin_client.post(
        "/api/v2/admin/messages/dm",
        json={"recipient_id": "u-coach", "body": "Please review the new lesson plan."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "dm"
    assert body["recipient_id"] == "u-coach"


def test_list_messages_includes_own_and_broadcasts(admin_client):
    admin_client.post("/api/v2/admin/messages/broadcast", json={"body": "All hands"})
    admin_client.post(
        "/api/v2/admin/messages/dm",
        json={"recipient_id": "u-admin", "body": "FYI"},
    )
    r = admin_client.get("/api/v2/admin/messages")
    assert r.status_code == 200
    bodies = {m["body"] for m in r.json()["messages"]}
    assert "All hands" in bodies
    assert "FYI" in bodies


# --------------------------------------------------------------------------
# Unread state on the admin DM surface (#864)
# --------------------------------------------------------------------------


def _seed_dm(client, *, message_id, sender_id, recipient_id, body, read_by=()):
    """Put one DM straight into the store, from either direction.

    The admin DM endpoint can only send *from* the admin, so a parent's reply
    has to be seeded rather than posted. Writing the domain object keeps the
    fake repo and the Mongo one reading the same document shape.
    """
    client.seed["messages"].rows[message_id] = Message(
        message_id=message_id,
        academy_id="acad",
        kind="dm",
        sender_id=sender_id,
        sender_persona="parent" if sender_id != "u-admin" else "admin",
        recipient_id=recipient_id,
        body=body,
        created_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        read_by=list(read_by),
    )


def test_list_messages_flags_an_incoming_dm_as_unread(admin_client):
    """An unread parent reply is the one thing the thread list must surface.

    Both halves of the conversation are listed and both carry the same
    `counterparty_id`, so the page can group a thread by the family rather
    than by `recipient_id` (which is the admin on every inbound message).
    """
    _seed_dm(
        admin_client,
        message_id="m-in",
        sender_id="p-1",
        recipient_id="u-admin",
        body="Can Ana switch to Thursday?",
    )
    _seed_dm(
        admin_client,
        message_id="m-out",
        sender_id="u-admin",
        recipient_id="p-1",
        body="Checking the Thursday roster now.",
    )

    r = admin_client.get("/api/v2/admin/messages")
    assert r.status_code == 200, r.text
    by_id = {m["message_id"]: m for m in r.json()["messages"]}

    assert by_id["m-in"]["is_read"] is False
    assert by_id["m-in"]["counterparty_id"] == "p-1"
    # Our own send is never "unread" and belongs to the same thread.
    assert by_id["m-out"]["is_read"] is True
    assert by_id["m-out"]["counterparty_id"] == "p-1"


def test_broadcasts_are_never_unread(admin_client):
    admin_client.post("/api/v2/admin/messages/broadcast", json={"body": "All hands"})

    r = admin_client.get("/api/v2/admin/messages")
    announcement = next(m for m in r.json()["messages"] if m["is_broadcast"])
    assert announcement["is_read"] is True
    assert announcement["counterparty_id"] is None


def test_mark_dm_read_clears_the_unread_flag(admin_client):
    _seed_dm(
        admin_client,
        message_id="m-in",
        sender_id="p-1",
        recipient_id="u-admin",
        body="Can Ana switch to Thursday?",
    )

    r = admin_client.post("/api/v2/admin/messages/m-in/read")
    assert r.status_code == 200, r.text

    listed = admin_client.get("/api/v2/admin/messages").json()["messages"]
    assert next(m for m in listed if m["message_id"] == "m-in")["is_read"] is True


def test_mark_dm_read_is_idempotent(admin_client):
    _seed_dm(
        admin_client,
        message_id="m-in",
        sender_id="p-1",
        recipient_id="u-admin",
        body="Hello",
    )

    admin_client.post("/api/v2/admin/messages/m-in/read")
    admin_client.post("/api/v2/admin/messages/m-in/read")

    assert admin_client.seed["messages"].rows["m-in"].read_by == ["u-admin"]


def test_mark_dm_read_cannot_stamp_someone_elses_dm(admin_client):
    """Same predicate as the read: a DM between two other people is a no-op."""
    _seed_dm(
        admin_client,
        message_id="m-other",
        sender_id="p-1",
        recipient_id="p-2",
        body="Not for the admin",
    )

    r = admin_client.post("/api/v2/admin/messages/m-other/read")

    assert r.status_code == 200, r.text
    assert admin_client.seed["messages"].rows["m-other"].read_by == []


def test_mark_dm_read_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post("/api/v2/admin/messages/m-in/read")
    assert r.status_code == 404


def test_broadcast_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post("/api/v2/admin/messages/broadcast", json={"body": "x"})
    assert r.status_code == 404


def test_dm_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/messages/dm", json={"recipient_id": "u-coach", "body": "x"}
    )
    assert r.status_code == 404


def test_list_messages_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/messages")
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Coach digest test-send + delivery log (Stream 2 C/D)
# --------------------------------------------------------------------------


@dataclass
class _FakeTestSend:
    calls: list[Any] = field(default_factory=list)
    result: SendCoachDigestTestResult = field(
        default_factory=lambda: SendCoachDigestTestResult(
            status="sent", coach_id="coach-1", email="c1@example.test"
        )
    )
    raises: Exception | None = None

    async def execute(self, command):
        self.calls.append(command)
        if self.raises is not None:
            raise self.raises
        return self.result


@dataclass
class _FakeDeliveryLog:
    rows: list[Any] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)

    async def execute(self, academy_id, *, limit=20):
        self.calls.append((academy_id, limit))
        return list(self.rows)


def _log_row(**overrides):
    base = dict(
        digest_id="dg-1",
        coach_id="coach-1",
        coach_email="c1@example.test",
        digest_date="2026-06-13",
        status="sent",
        kind="daily",
        sent_at="2026-06-13T06:00:00Z",
        failed_reason=None,
        created_at=datetime(2026, 6, 13, 6, 0, tzinfo=UTC),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_digest_test_send_to_named_coach(admin_client):
    fake = _FakeTestSend()
    admin_client.use_cases.send_coach_digest_test = fake

    r = admin_client.post("/api/v2/admin/comms/digests/test-send", json={"coach_id": "coach-1"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sent"
    assert body["coach_id"] == "coach-1"
    assert fake.calls[0].target_user_id == "coach-1"
    assert fake.calls[0].academy_id == "acad"


def test_digest_test_send_uses_scheduler_timezone_date(admin_client, monkeypatch):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 6, 14, 4, 30, tzinfo=UTC)
            return value if tz is None else value.astimezone(tz)

    fake = _FakeTestSend()
    admin_client.use_cases.send_coach_digest_test = fake
    monkeypatch.setenv("SCHEDULER_TZ", "America/Chicago")
    get_settings.cache_clear()
    monkeypatch.setattr(comms_routes, "datetime", _FixedDateTime)

    try:
        r = admin_client.post("/api/v2/admin/comms/digests/test-send", json={"coach_id": "coach-1"})
    finally:
        get_settings.cache_clear()

    assert r.status_code == 200, r.text
    assert fake.calls[0].on_date.isoformat() == "2026-06-13"


def test_digest_test_send_accepts_explicit_test_date(admin_client):
    fake = _FakeTestSend()
    admin_client.use_cases.send_coach_digest_test = fake

    r = admin_client.post(
        "/api/v2/admin/comms/digests/test-send",
        json={"coach_id": "coach-1", "on_date": "2026-06-20"},
    )

    assert r.status_code == 200, r.text
    assert fake.calls[0].target_user_id == "coach-1"
    assert fake.calls[0].on_date.isoformat() == "2026-06-20"


def test_digest_test_send_to_self_uses_admin_user_id(admin_client):
    fake = _FakeTestSend(
        result=SendCoachDigestTestResult(status="sent", coach_id="u-admin", email="admin@x.test")
    )
    admin_client.use_cases.send_coach_digest_test = fake

    r = admin_client.post("/api/v2/admin/comms/digests/test-send", json={})

    assert r.status_code == 200, r.text
    # "self"/omitted resolves to the admin's own user_id.
    assert fake.calls[0].target_user_id == "u-admin"


def test_digest_test_send_unknown_coach_404(admin_client):
    admin_client.use_cases.send_coach_digest_test = _FakeTestSend(
        raises=CoachDigestTargetNotFound("nope")
    )

    r = admin_client.post("/api/v2/admin/comms/digests/test-send", json={"coach_id": "nope"})

    assert r.status_code == 404, r.text


def test_digest_test_send_not_configured_503(admin_client):
    admin_client.use_cases.send_coach_digest_test = None

    r = admin_client.post("/api/v2/admin/comms/digests/test-send", json={"coach_id": "coach-1"})

    assert r.status_code == 503, r.text


def test_digest_test_send_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post(
        "/api/v2/admin/comms/digests/test-send", json={"coach_id": "coach-1"}
    )
    assert r.status_code == 404


def test_digest_log_returns_recent_entries(admin_client):
    fake = _FakeDeliveryLog(
        rows=[
            _log_row(digest_id="dg-2", kind="test", status="sent"),
            _log_row(digest_id="dg-1", status="skipped_empty", sent_at=None),
        ]
    )
    admin_client.use_cases.get_digest_delivery_log = fake

    r = admin_client.get("/api/v2/admin/comms/digests/log")

    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    assert [e["digest_id"] for e in entries] == ["dg-2", "dg-1"]
    assert entries[0]["kind"] == "test"
    assert entries[1]["status"] == "skipped_empty"
    assert fake.calls[0] == ("acad", 20)


def test_digest_log_clamps_limit(admin_client):
    fake = _FakeDeliveryLog(rows=[])
    admin_client.use_cases.get_digest_delivery_log = fake

    r = admin_client.get("/api/v2/admin/comms/digests/log?limit=999")

    assert r.status_code == 200, r.text
    assert fake.calls[0] == ("acad", 100)


def test_digest_log_not_configured_503(admin_client):
    admin_client.use_cases.get_digest_delivery_log = None

    r = admin_client.get("/api/v2/admin/comms/digests/log")

    assert r.status_code == 503, r.text


def test_digest_log_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.get("/api/v2/admin/comms/digests/log")
    assert r.status_code == 404
