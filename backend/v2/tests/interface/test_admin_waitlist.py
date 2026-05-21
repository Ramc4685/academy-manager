"""Admin waitlist BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry


def _add(seed, waitlist_id: str, joined_at: datetime, status: str = "waiting"):
    seed["waitlist"].entries[waitlist_id] = WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=f"st-{waitlist_id}",
        parent_id=f"p-{waitlist_id}",
        joined_at=joined_at,
        status=status,  # type: ignore[arg-type]
    )


def test_list_waitlist_returns_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))
    r = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {e["waitlist_id"] for e in body["entries"]}
    assert ids == {"w1", "w2"}


def test_list_global_waitlist_groups_waiting_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    r = admin_client.get("/api/v2/admin/waitlist")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_waitlisted"] == 2
    assert body["sessions"][0]["session_id"] == "sess-1"
    assert [entry["waitlist_id"] for entry in body["sessions"][0]["entries"]] == [
        "w1",
        "w2",
    ]


def test_list_waitlist_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 404


def test_promote_picks_oldest_fifo(admin_client):
    older = datetime(2026, 5, 16, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)
    _add(admin_client.seed, "older", older)
    _add(admin_client.seed, "newer", newer)
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200, r.text
    assert r.json()["promoted_waitlist_id"] == "older"
    assert admin_client.seed["waitlist"].entries["older"].status == "promoted"


def test_promote_empty_waitlist_returns_null(admin_client):
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200
    assert r.json()["promoted_waitlist_id"] is None


def test_skip_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.post("/api/v2/admin/waitlist/w1/skip")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "skipped"


def test_remove_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.delete("/api/v2/admin/waitlist/w1")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "removed"


def test_promote_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 404
