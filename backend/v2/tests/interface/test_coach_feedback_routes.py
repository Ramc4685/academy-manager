"""Interface tests for POST/GET /coach/sessions/{id}/feedback."""

from __future__ import annotations

# coach_client, parent_client, admin_client, anon_client are provided by conftest.py


def test_post_feedback_creates_201(coach_client):
    resp = coach_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st1", "body": "Great footwork today!", "rating": 4},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["session_id"] == "s-today-1"
    assert data["student_id"] == "st1"
    assert data["body"] == "Great footwork today!"
    assert data["rating"] == 4
    assert "feedback_id" in data
    assert "created_at" in data


def test_post_feedback_no_rating(coach_client):
    resp = coach_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st2", "body": "Needs to work on serve."},
    )
    assert resp.status_code == 201
    assert resp.json()["rating"] is None


def test_post_feedback_unassigned_session_returns_409(coach_client):
    """coach-1 is not assigned to s-other-coach → SessionNotAssigned → 409."""
    resp = coach_client.post(
        "/api/v2/coach/sessions/s-other-coach/feedback",
        json={"student_id": "st1", "body": "Some comment"},
    )
    assert resp.status_code == 409


def test_get_feedback_lists_posted(coach_client):
    # Post two entries
    coach_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st1", "body": "First note"},
    )
    coach_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st2", "body": "Second note"},
    )

    resp = coach_client.get("/api/v2/coach/sessions/s-today-1/feedback")
    assert resp.status_code == 200
    data = resp.json()
    assert "feedback" in data
    assert len(data["feedback"]) == 2


def test_get_feedback_empty_session(coach_client):
    resp = coach_client.get("/api/v2/coach/sessions/s-today-2/feedback")
    assert resp.status_code == 200
    assert resp.json()["feedback"] == []


def test_anon_post_returns_401(anon_client):
    resp = anon_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st1", "body": "Anon note"},
    )
    assert resp.status_code == 401


def test_anon_get_returns_401(anon_client):
    resp = anon_client.get("/api/v2/coach/sessions/s-today-1/feedback")
    assert resp.status_code == 401


def test_wrong_persona_post_returns_404(parent_client):
    """Parent hitting a coach route gets 404 (wrong persona)."""
    resp = parent_client.post(
        "/api/v2/coach/sessions/s-today-1/feedback",
        json={"student_id": "st1", "body": "Parent note"},
    )
    assert resp.status_code == 404


def test_wrong_persona_get_returns_404(parent_client):
    resp = parent_client.get("/api/v2/coach/sessions/s-today-1/feedback")
    assert resp.status_code == 404
