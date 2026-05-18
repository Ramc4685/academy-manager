"""Admin directory BFF routes."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models import Student


def test_admin_lists_coaches(admin_client):
    r = admin_client.get("/api/v2/admin/users?role=coach")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["users"] == [
        {
            "user_id": "coach-1",
            "email": "coach@example.com",
            "display_name": "Coach One",
            "role": "coach",
            "status": "active",
        }
    ]


def test_admin_lists_students(admin_client):
    admin_client.seed["students"].students["st-1"] = Student(
        student_id="st-1",
        academy_id="acad",
        parent_id="p-1",
        full_name="Alice",
    )
    r = admin_client.get("/api/v2/admin/students")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["students"][0]["student_id"] == "st-1"
    assert body["students"][0]["full_name"] == "Alice"
    assert body["students"][0]["parent_id"] == "p-1"


def test_directory_wrong_persona_404(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/users").status_code == 404
    assert coach_on_admin_client.get("/api/v2/admin/students").status_code == 404
