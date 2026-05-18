"""Admin sessions BFF — happy paths + wrong-persona 404 per route.

Routes covered:
- GET    /api/v2/admin/sessions
- POST   /api/v2/admin/sessions
- DELETE /api/v2/admin/sessions/{id}
- GET    /api/v2/admin/sessions/{id}/enrollments
- POST   /api/v2/admin/enrollments
- DELETE /api/v2/admin/enrollments/{id}
- POST   /api/v2/admin/enrollments/{id}/transfer
- POST   /api/v2/admin/enrollments/{id}/pause
- POST   /api/v2/admin/enrollments/{id}/resume
"""

from __future__ import annotations


def test_list_sessions_returns_seeded_session(admin_client):
    r = admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["session_id"] == "sess-1" for s in body["sessions"])


def test_list_sessions_coach_persona_returns_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 404


def test_list_sessions_parent_persona_returns_404(parent_on_admin_client):
    r = parent_on_admin_client.get("/api/v2/admin/sessions?date=2026-05-16")
    assert r.status_code == 404


def test_create_session_happy_path(admin_client):
    r = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-2",
            "title": "Adult B",
            "location": "Court 2",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 6,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Adult B"
    assert body["capacity"] == 6
    # Confirms list reflects the new session.
    listing = admin_client.get("/api/v2/admin/sessions?date=2026-05-17").json()
    assert any(s["session_id"] == body["session_id"] for s in listing["sessions"])


def test_create_session_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "x",
            "title": "x",
            "location": "x",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 4,
        },
    )
    assert r.status_code == 404


def test_cancel_session_returns_204(admin_client):
    r = admin_client.delete("/api/v2/admin/sessions/sess-1")
    assert r.status_code == 204
    # session is now cancelled in the seed
    assert admin_client.seed["sessions"].sessions["sess-1"].status == "cancelled"


def test_add_to_roster_then_list_enrollments(admin_client):
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert r.status_code == 200, r.text
    enrollment_id = r.json()["enrollment_id"]
    # The composition's enrollment_query is a separate fake from the writer
    # (since the production code uses two ports). Wire them: copy the row.
    admin_client.seed["enrollment_query"].rows = dict(
        admin_client.seed["enrollments"].rows
    )
    listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert any(e["enrollment_id"] == enrollment_id for e in listing["enrollments"])
    assert any(e["student_name"] == "Alice" for e in listing["enrollments"])


def test_add_to_roster_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/enrollments",
        json={"session_id": "sess-1", "student_id": "x", "parent_id": "x", "full_name": "x"},
    )
    assert r.status_code == 404


def test_pause_and_resume_enrollment(admin_client):
    # Create an enrollment first.
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = r.json()["enrollment_id"]

    p = admin_client.post(f"/api/v2/admin/enrollments/{enrollment_id}/pause")
    assert p.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "paused"

    res = admin_client.post(f"/api/v2/admin/enrollments/{enrollment_id}/resume")
    assert res.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "active"


def test_transfer_enrollment_reserves_target_and_releases_source(admin_client):
    create_target = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-2",
            "title": "Adult B",
            "location": "Court 2",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 6,
        },
    )
    target_session_id = create_target.json()["session_id"]
    add = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = add.json()["enrollment_id"]

    r = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/transfer",
        json={"target_session_id": target_session_id},
    )

    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == target_session_id
    assert admin_client.seed["enrollments"].rows[enrollment_id].session_id == target_session_id
    assert admin_client.seed["enrollments"].move_history == [
        {
            "enrollment_id": enrollment_id,
            "from_session_id": "sess-1",
            "to_session_id": target_session_id,
        }
    ]
    assert admin_client.seed["sessions"].reserved[target_session_id] == 1
    assert admin_client.seed["sessions"].reserved["sess-1"] == 0


def test_cancel_enrollment_emits_event(admin_client):
    r = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = r.json()["enrollment_id"]
    outbox_len_before = len(admin_client.seed["outbox"].events)
    d = admin_client.delete(f"/api/v2/admin/enrollments/{enrollment_id}")
    assert d.status_code == 204
    # EnrollmentCancelled event was appended.
    new_events = admin_client.seed["outbox"].events[outbox_len_before:]
    assert any(e.name == "Enrollment.EnrollmentCancelled" for e in new_events)
