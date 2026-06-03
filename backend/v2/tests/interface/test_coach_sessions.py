"""Interface tests for GET /api/v2/coach/sessions."""

from __future__ import annotations


def test_coach_sessions_returns_upcoming_occurrences(coach_client):
    r = coach_client.get("/api/v2/coach/sessions")
    assert r.status_code == 200, r.text

    body = r.json()
    session_ids = [s["session_id"] for s in body["sessions"]]
    occurrence_ids = [s["occurrence_id"] for s in body["sessions"]]

    assert session_ids == ["s-today-1", "s-today-2"]
    assert occurrence_ids == ["occ-today-1", "occ-today-2"]
    assert "s-other-coach" not in session_ids


def test_coach_sessions_parent_persona_returns_404(parent_client):
    r = parent_client.get("/api/v2/coach/sessions")
    assert r.status_code == 404


def test_coach_sessions_unauthenticated_returns_401(anon_client):
    r = anon_client.get("/api/v2/coach/sessions")
    assert r.status_code == 401
