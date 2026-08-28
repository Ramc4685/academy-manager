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
    assert body["students"][0]["attendance_rate"] is None
    assert body["students"][0]["dues_status"] == "current"
    assert body["next_cursor"] is None


def test_admin_students_supports_search_status_and_limit(admin_client):
    admin_client.seed["students"].students["st-1"] = Student(
        student_id="st-1",
        academy_id="acad",
        parent_id="p-1",
        full_name="Alice Chen",
    )
    admin_client.seed["students"].students["st-2"] = Student(
        student_id="st-2",
        academy_id="acad",
        parent_id="p-2",
        full_name="Bob Rao",
    )
    admin_client.seed["students"].admin_status["st-2"] = "paused"

    r = admin_client.get("/api/v2/admin/students?search=ali&status=active&limit=1")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["student_id"] for s in body["students"]] == ["st-1"]
    assert body["students"][0]["parent_name"] == "Parent One"
    assert body["next_cursor"] is None


def test_admin_students_returns_cursor_for_next_page(admin_client):
    for student_id, name in [
        ("st-1", "Alice Chen"),
        ("st-2", "Bob Rao"),
        ("st-3", "Cora Iyer"),
    ]:
        admin_client.seed["students"].students[student_id] = Student(
            student_id=student_id,
            academy_id="acad",
            parent_id="p-1",
            full_name=name,
        )

    first = admin_client.get("/api/v2/admin/students?limit=2")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert [s["student_id"] for s in first_body["students"]] == ["st-1", "st-2"]
    assert first_body["next_cursor"]

    second = admin_client.get(f"/api/v2/admin/students?limit=2&cursor={first_body['next_cursor']}")
    assert second.status_code == 200, second.text
    assert [s["student_id"] for s in second.json()["students"]] == ["st-3"]
    assert second.json()["next_cursor"] is None


def test_admin_students_rejects_malformed_cursor(admin_client):
    r = admin_client.get("/api/v2/admin/students?cursor=not-a-valid-cursor")

    assert r.status_code == 400


def test_admin_students_missing_filter_accepts_known_fields(admin_client):
    """Issue #380 gap report — the query param round-trips through to the
    use case without erroring for a real completeness field."""
    r = admin_client.get("/api/v2/admin/students?missing=date_of_birth,emergency_contact_name")

    assert r.status_code == 200


def test_admin_students_missing_filter_rejects_unknown_field(admin_client):
    r = admin_client.get("/api/v2/admin/students?missing=not_a_real_field")

    assert r.status_code == 400


def test_directory_wrong_persona_404(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/users").status_code == 404
    assert coach_on_admin_client.get("/api/v2/admin/students").status_code == 404


def test_admin_resends_login_invite(admin_client):
    r = admin_client.post("/api/v2/admin/users/coach-1/login-invite")
    assert r.status_code == 200, r.text
    assert r.json()["sent_at"] is not None


def test_login_invite_unknown_user_404(admin_client):
    r = admin_client.post("/api/v2/admin/users/nope/login-invite")
    assert r.status_code == 404


def test_login_invite_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post("/api/v2/admin/users/coach-1/login-invite")
    assert r.status_code == 404


def test_admin_adds_role_to_user(admin_client):
    r = admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "parent", "reason": "Coach is also a parent"},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["roles"]) == {"coach", "parent"}


def test_admin_removes_role_from_user(admin_client):
    admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "parent", "reason": "setup"},
    )
    r = admin_client.delete(
        "/api/v2/admin/users/coach-1/roles/parent?reason=No%20longer%20a%20parent"
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["coach"]


def test_admin_cannot_remove_own_admin_role(admin_client):
    # admin_client's claims user_id — see conftest _claims(): f"u-admin"
    r = admin_client.delete("/api/v2/admin/users/u-admin/roles/admin?reason=x")
    assert r.status_code == 409


def test_cannot_remove_last_role(admin_client):
    r = admin_client.delete("/api/v2/admin/users/coach-1/roles/coach?reason=x")
    assert r.status_code == 409


def test_role_endpoints_wrong_persona_404(coach_on_admin_client):
    assert (
        coach_on_admin_client.post(
            "/api/v2/admin/users/coach-1/roles", json={"role": "parent", "reason": "x"}
        ).status_code
        == 404
    )
