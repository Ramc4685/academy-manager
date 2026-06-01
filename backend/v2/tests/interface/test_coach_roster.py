"""Interface tests for coach roster routes.

GET  /api/v2/coach/sessions/{session_id}/roster
POST /api/v2/coach/sessions/{session_id}/roster
DELETE /api/v2/coach/sessions/{session_id}/roster/{student_id}

Scenarios:
- assigned coach can view roster
- assigned coach can add a student
- assigned coach can remove an enrolled student
- unassigned coach gets 403
- parent persona gets 404 (wrong persona, route invisible)
- admin persona gets 404 (wrong persona, route invisible)
- anonymous gets 401
"""

from __future__ import annotations


SESSION_ID = "s-today-1"
OTHER_SESSION_ID = "s-other-coach"


# ---------- GET roster ----------


def test_get_roster_happy_path(coach_client):
    r = coach_client.get(f"/api/v2/coach/sessions/{SESSION_ID}/roster")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "roster" in body
    entries = body["roster"]
    assert len(entries) == 2
    student_ids = {e["student_id"] for e in entries}
    assert student_ids == {"st1", "st2"}
    for entry in entries:
        assert "student_id" in entry
        assert "full_name" in entry
        assert "enrollment_status" in entry


def test_get_roster_unassigned_coach_returns_403(coach_client):
    r = coach_client.get(f"/api/v2/coach/sessions/{OTHER_SESSION_ID}/roster")
    assert r.status_code == 403, r.text


def test_get_roster_parent_persona_returns_404(parent_client):
    r = parent_client.get(f"/api/v2/coach/sessions/{SESSION_ID}/roster")
    assert r.status_code == 404


def test_get_roster_admin_persona_returns_404(admin_client):
    r = admin_client.get(f"/api/v2/coach/sessions/{SESSION_ID}/roster")
    assert r.status_code == 404


def test_get_roster_unauthenticated_returns_401(anon_client):
    r = anon_client.get(f"/api/v2/coach/sessions/{SESSION_ID}/roster")
    assert r.status_code == 401


# ---------- POST roster (add student) ----------


def test_add_student_to_roster_happy_path(coach_client):
    body = {"student_id": "st-new", "parent_id": "p3", "full_name": "Charlie"}
    r = coach_client.post(f"/api/v2/coach/sessions/{SESSION_ID}/roster", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["session_id"] == SESSION_ID
    assert data["student_id"] == "st-new"
    assert data["status"] == "active"


def test_add_student_unassigned_coach_returns_403(coach_client):
    body = {"student_id": "st-new", "parent_id": "p3", "full_name": "Charlie"}
    r = coach_client.post(f"/api/v2/coach/sessions/{OTHER_SESSION_ID}/roster", json=body)
    assert r.status_code == 403, r.text


def test_add_student_parent_persona_returns_404(parent_client):
    body = {"student_id": "st-new", "parent_id": "p3", "full_name": "Charlie"}
    r = parent_client.post(f"/api/v2/coach/sessions/{SESSION_ID}/roster", json=body)
    assert r.status_code == 404


def test_add_student_admin_persona_returns_404(admin_client):
    body = {"student_id": "st-new", "parent_id": "p3", "full_name": "Charlie"}
    r = admin_client.post(f"/api/v2/coach/sessions/{SESSION_ID}/roster", json=body)
    assert r.status_code == 404


def test_add_student_unauthenticated_returns_401(anon_client):
    body = {"student_id": "st-new", "parent_id": "p3", "full_name": "Charlie"}
    r = anon_client.post(f"/api/v2/coach/sessions/{SESSION_ID}/roster", json=body)
    assert r.status_code == 401


# ---------- DELETE roster (remove student) ----------


def test_remove_student_from_roster_happy_path(coach_client):
    r = coach_client.delete(f"/api/v2/coach/sessions/{SESSION_ID}/roster/st1")
    assert r.status_code == 204, r.text


def test_remove_student_unassigned_coach_returns_403(coach_client):
    r = coach_client.delete(f"/api/v2/coach/sessions/{OTHER_SESSION_ID}/roster/st1")
    assert r.status_code == 403, r.text


def test_remove_student_not_enrolled_returns_404(coach_client):
    r = coach_client.delete(f"/api/v2/coach/sessions/{SESSION_ID}/roster/st-ghost")
    assert r.status_code == 404, r.text


def test_remove_student_parent_persona_returns_404(parent_client):
    r = parent_client.delete(f"/api/v2/coach/sessions/{SESSION_ID}/roster/st1")
    assert r.status_code == 404


def test_remove_student_admin_persona_returns_404(admin_client):
    r = admin_client.delete(f"/api/v2/coach/sessions/{SESSION_ID}/roster/st1")
    assert r.status_code == 404


def test_remove_student_unauthenticated_returns_401(anon_client):
    r = anon_client.delete(f"/api/v2/coach/sessions/{SESSION_ID}/roster/st1")
    assert r.status_code == 401
