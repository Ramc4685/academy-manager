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
            "roles": ["coach"],
        }
    ]


def _ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [u["user_id"] for u in response.json()["users"]]


def test_admin_users_exclude_role_parent_keeps_parent_who_also_coaches(admin_client):
    """Sidebar regroup spec 4.1: drop a user only when they hold no role other
    than the excluded one. ``pc-1`` is primary-role parent but also a coach."""
    ids = _ids(admin_client.get("/api/v2/admin/users?exclude_role=parent"))

    assert "p-1" not in ids
    assert set(ids) == {"coach-1", "adm", "pc-1", "ps-1"}


def test_admin_users_roles_is_a_union_filter(admin_client):
    ids = _ids(admin_client.get("/api/v2/admin/users?roles=coach&roles=admin"))

    assert set(ids) == {"coach-1", "adm", "pc-1"}
    assert "p-1" not in ids


def test_admin_users_roles_and_exclude_role_combine_with_and(admin_client):
    ids = _ids(admin_client.get("/api/v2/admin/users?roles=parent&exclude_role=parent"))

    # Hold parent, but are kept only because they hold another role too.
    assert ids == ["pc-1", "ps-1"]


def test_admin_users_role_and_exclude_role_combine_with_and(admin_client):
    # Primary role parent, excluded unless another role is held.
    ids = _ids(admin_client.get("/api/v2/admin/users?role=parent&exclude_role=parent"))

    assert ids == ["pc-1", "ps-1"]


def test_admin_users_list_payload_carries_every_held_role(admin_client):
    r = admin_client.get("/api/v2/admin/users")
    assert r.status_code == 200, r.text
    by_id = {u["user_id"]: u for u in r.json()["users"]}

    assert by_id["pc-1"]["role"] == "parent"
    assert by_id["pc-1"]["roles"] == ["parent", "coach"]


def test_admin_users_list_survives_a_row_holding_the_student_role(admin_client):
    """A ``users`` doc can hold ``student`` next to ``parent`` (a former student
    who later registered as a parent). ``student`` is not a role an admin can
    assign, but the read model must still render the row instead of failing
    the whole list with a validation error."""
    r = admin_client.get("/api/v2/admin/users")
    assert r.status_code == 200, r.text
    by_id = {u["user_id"]: u for u in r.json()["users"]}

    assert by_id["ps-1"]["role"] == "parent"
    assert by_id["ps-1"]["roles"] == ["parent", "student"]

    # Filters that an admin can express still refuse ``student`` as input.
    assert admin_client.get("/api/v2/admin/users?roles=student").status_code == 422
    assert admin_client.get("/api/v2/admin/users?role=student").status_code == 422


def test_admin_users_rejects_unknown_exclude_role(admin_client):
    assert admin_client.get("/api/v2/admin/users?exclude_role=coach").status_code == 422
    assert admin_client.get("/api/v2/admin/users?exclude_role=nope").status_code == 422


def test_admin_users_rejects_unknown_roles_value(admin_client):
    assert admin_client.get("/api/v2/admin/users?roles=coach&roles=janitor").status_code == 422


def test_admin_users_new_params_still_404_for_wrong_persona(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/users?exclude_role=parent&roles=coach")

    assert r.status_code == 404


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
    # Issue #773: the derived lifecycle replaces the free-text students.status.
    assert body["students"][0]["lifecycle"] == "active"
    assert "status" not in body["students"][0]
    assert body["next_cursor"] is None


def test_admin_students_supports_search_lifecycle_and_limit(admin_client):
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
    admin_client.seed["students"].admin_lifecycle["st-2"] = "paused"

    r = admin_client.get("/api/v2/admin/students?search=ali&lifecycle=active&limit=1")

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


def test_email_edit_auto_sends_one_login_invite(admin_client):
    """#436: the Firebase email change clears `email_verified`, so the edit
    must carry a fresh set-password link or the parent silently loses
    password login."""
    sender = admin_client.use_cases.send_login_invite
    before = list(sender.sent)

    r = admin_client.patch(
        "/api/v2/admin/users/p-1",
        json={"email": "corrected@example.com", "reason": "typo in email"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "corrected@example.com"
    assert body["login_invite"]["status"] == "sent"
    assert body["login_invite"]["sent_at"] is not None
    assert [u for u in sender.sent if u not in before] == ["p-1"]


def test_non_email_edit_does_not_re_invite(admin_client):
    sender = admin_client.use_cases.send_login_invite
    before = list(sender.sent)

    r = admin_client.patch(
        "/api/v2/admin/users/p-1",
        json={"display_name": "Parent Renamed", "reason": "name change"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["login_invite"]["status"] == "not_needed"
    assert sender.sent == before


def test_failed_re_invite_is_reported_to_the_admin(admin_client):
    """The edit itself committed, so this stays a 200 — but the admin must
    see that the parent never got a working link, not a silent success."""
    r = admin_client.patch(
        "/api/v2/admin/users/p-2",
        json={"email": "corrected2@example.com", "reason": "typo in email"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "corrected2@example.com"
    assert body["login_invite"]["status"] == "failed"
    assert body["login_invite"]["error"]
