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
