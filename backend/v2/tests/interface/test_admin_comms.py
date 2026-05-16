"""Admin comms BFF — broadcast + DM + inbox."""

from __future__ import annotations


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
