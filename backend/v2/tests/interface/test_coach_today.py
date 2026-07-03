"""Interface tests for GET /api/v2/coach/today.

Covers happy path, empty day, wrong-persona 404 (security matrix), and
unauthenticated 401.
"""

from __future__ import annotations


def test_coach_today_happy_path(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-05-16"
    session_ids = [s["session_id"] for s in body["sessions"]]
    assert session_ids == ["s-today-1", "s-today-2"]
    occurrence_ids = [s["occurrence_id"] for s in body["sessions"]]
    assert occurrence_ids == ["occ-today-1", "occ-today-2"]
    # Coach BFF must not leak other coaches' sessions.
    assert "s-other-coach" not in session_ids
    # Roster is composed for assigned sessions.
    first = body["sessions"][0]
    assert {r["full_name"] for r in first["roster"]} == {"Alice", "Bob"}


def test_coach_today_hydrates_existing_attendance(coach_client):
    """A recorded mark must come back on /today so reloads don't render a
    marked class as unmarked (and bulk mark-all doesn't 409 on re-send)."""
    mark = coach_client.post(
        "/api/v2/coach/attendance",
        json={
            "mutation_id": "01HTESTHYDRATE0000000000001",
            "occurrence_id": "occ-today-1",
            "session_id": "s-today-1",
            "student_id": "st1",
            "status": "present",
        },
    )
    assert mark.status_code in (200, 201), mark.text

    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert by_id["st1"]["attendance_status"] == "present"
    unmarked = [e for sid, e in by_id.items() if sid != "st1"]
    assert all(e["attendance_status"] is None for e in unmarked)


def test_coach_today_other_day_empty(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-17")
    assert r.status_code == 200
    assert r.json() == {"date": "2026-05-17", "sessions": []}


def test_coach_today_default_date_is_today(coach_client):
    r = coach_client.get("/api/v2/coach/today")
    assert r.status_code == 200


def test_coach_today_parent_persona_returns_404(parent_client):
    r = parent_client.get("/api/v2/coach/today")
    assert r.status_code == 404
    assert "/coach/" not in r.text.lower() or r.json().get("detail") == "Not found"


def test_coach_today_admin_persona_returns_404(admin_client):
    r = admin_client.get("/api/v2/coach/today")
    assert r.status_code == 404


def test_coach_today_unauthenticated_returns_401(anon_client):
    r = anon_client.get("/api/v2/coach/today")
    assert r.status_code == 401
