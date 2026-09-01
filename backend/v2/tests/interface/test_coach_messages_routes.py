"""Interface tests for GET /coach/messages and POST /coach/messages/{id}/read."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.shared.comms import Message


def _message(**overrides) -> Message:
    base = dict(
        message_id="m-1",
        academy_id="test-academy",
        kind="dm",
        sender_id="adm",
        sender_persona="admin",
        recipient_id="coach-1",
        body="Please review the roster",
        created_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
        read_by=[],
    )
    base.update(overrides)
    return Message(**base)


def test_coach_sees_own_dms_and_announcements(coach_client):
    coach_client.messages_repo.rows["m-1"] = _message(message_id="m-1")
    coach_client.messages_repo.rows["m-2"] = _message(
        message_id="m-2", kind="announcement", recipient_id=None, body="Tournament Saturday"
    )
    coach_client.messages_repo.rows["m-3"] = _message(
        message_id="m-3", recipient_id="coach-2", body="Not for coach-1"
    )

    r = coach_client.get("/api/v2/coach/messages")

    assert r.status_code == 200, r.text
    bodies = {m["body"] for m in r.json()["messages"]}
    assert bodies == {"Please review the roster", "Tournament Saturday"}


def test_coach_message_read_flag_reflects_read_by(coach_client):
    coach_client.messages_repo.rows["m-1"] = _message(message_id="m-1", read_by=["coach-1"])
    coach_client.messages_repo.rows["m-2"] = _message(message_id="m-2", read_by=[])

    r = coach_client.get("/api/v2/coach/messages")

    assert r.status_code == 200, r.text
    by_id = {m["message_id"]: m["read"] for m in r.json()["messages"]}
    assert by_id == {"m-1": True, "m-2": False}


def test_coach_mark_message_read_is_idempotent(coach_client):
    coach_client.messages_repo.rows["m-1"] = _message(message_id="m-1", read_by=[])

    r1 = coach_client.post("/api/v2/coach/messages/m-1/read")
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "ok"

    r2 = coach_client.post("/api/v2/coach/messages/m-1/read")
    assert r2.status_code == 200, r2.text

    stored = coach_client.messages_repo.rows["m-1"]
    assert stored.read_by == ["coach-1"]


def test_coach_cannot_see_other_coachs_dm(coach_client):
    coach_client.messages_repo.rows["m-1"] = _message(
        message_id="m-1", recipient_id="coach-2", body="Only for coach-2"
    )

    r = coach_client.get("/api/v2/coach/messages")

    assert r.status_code == 200, r.text
    assert r.json()["messages"] == []


def test_coach_mark_read_on_unreadable_dm_is_a_noop(coach_client):
    """A DM addressed to someone else cannot be stamped as read.

    Without recipient scoping on the update, any coach in the academy could
    $addToSet their own id onto another user's DM — a forged read receipt.
    The response is deliberately identical to the success case so the route
    is not an existence oracle.
    """
    coach_client.messages_repo.rows["m-1"] = _message(
        message_id="m-1", recipient_id="coach-2", body="Only for coach-2"
    )

    r = coach_client.post("/api/v2/coach/messages/m-1/read")

    assert r.status_code == 200, r.text
    assert coach_client.messages_repo.rows["m-1"].read_by == []


def test_coach_mark_read_on_unknown_message_is_a_noop(coach_client):
    r = coach_client.post("/api/v2/coach/messages/does-not-exist/read")
    assert r.status_code == 200, r.text


def test_coach_can_mark_announcement_read(coach_client):
    coach_client.messages_repo.rows["m-1"] = _message(
        message_id="m-1", kind="announcement", recipient_id=None, body="All hands"
    )

    r = coach_client.post("/api/v2/coach/messages/m-1/read")

    assert r.status_code == 200, r.text
    assert coach_client.messages_repo.rows["m-1"].read_by == ["coach-1"]


def test_coach_messages_wrong_persona_404(parent_client):
    r = parent_client.get("/api/v2/coach/messages")
    assert r.status_code == 404


def test_coach_mark_read_wrong_persona_404(parent_client):
    r = parent_client.post("/api/v2/coach/messages/m-1/read")
    assert r.status_code == 404


def test_coach_messages_requires_auth(anon_client):
    r = anon_client.get("/api/v2/coach/messages")
    assert r.status_code == 401


# --- #614 session announcement scoping ---------------------------------


def _session_announcement(session_id: str = "s-today-1", **overrides) -> Message:
    fields = dict(
        message_id="ann-1",
        kind="announcement",
        recipient_id=None,
        body="Court 3 is closed tonight",
        scope_type="session",
        scope_id=session_id,
        scope_label="Junior A",
    )
    fields.update(overrides)
    return _message(**fields)


def test_assigned_coach_sees_the_session_announcement(coach_client):
    # `coach-1` is the coach_id on s-today-1 in the shared seed.
    coach_client.messages_repo.rows["ann-1"] = _session_announcement()

    r = coach_client.get("/api/v2/coach/messages")

    assert r.status_code == 200, r.text
    [view] = r.json()["messages"]
    assert view["scope_label"] == "Junior A"


def test_coach_does_not_see_another_coachs_session_announcement(coach_client):
    coach_client.messages_repo.rows["ann-1"] = _session_announcement(
        session_id="s-not-mine", scope_label="Someone else's class"
    )
    coach_client.messages_repo.rows["m-2"] = _message(
        message_id="m-2", kind="announcement", recipient_id=None, body="Academy closed"
    )

    r = coach_client.get("/api/v2/coach/messages")

    assert r.status_code == 200, r.text
    # The academy-wide announcement is untouched by the new scoping.
    assert [m["body"] for m in r.json()["messages"]] == ["Academy closed"]
