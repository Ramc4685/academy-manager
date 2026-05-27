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


def test_list_session_occurrences_shows_assignment_state(admin_client):
    r = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrences"] == [
        {
            "occurrence_id": "occ-admin-1",
            "session_id": "sess-1",
            "start_at": "2026-05-16T09:00:00Z",
            "end_at": "2026-05-16T10:30:00Z",
            "status": "scheduled",
            "scheduled_coach_id": "coach-1",
            "actual_coach_id": None,
            "substitute_coach_id": None,
            "attendance_marked_count": 0,
            "attendance_marked_by": [],
            "attendance_last_marked_at": None,
        }
    ]


def test_update_session_occurrence_actual_coach(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/session-occurrences/occ-admin-1/coach",
        json={
            "actual_coach_id": "coach-2",
            "substitute_coach_id": "coach-3",
            "reason": "substitute",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrence_id"] == "occ-admin-1"
    assert body["actual_coach_id"] == "coach-2"
    assert body["substitute_coach_id"] == "coach-3"
    assert admin_client.seed["occurrences"].rows["occ-admin-1"].actual_coach_id == "coach-2"
    assert admin_client.seed["occurrences"].rows["occ-admin-1"].substitute_coach_id == "coach-3"


def test_list_session_occurrences_wrong_persona_returns_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions/sess-1/occurrences")
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
    admin_client.seed["enrollment_query"].rows = dict(admin_client.seed["enrollments"].rows)
    listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert any(e["enrollment_id"] == enrollment_id for e in listing["enrollments"])
    assert any(e["student_name"] == "Alice" for e in listing["enrollments"])


def test_list_enrollments_includes_level_and_dues_status(admin_client):
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
    admin_client.seed["enrollment_query"].rows = dict(admin_client.seed["enrollments"].rows)
    admin_client.seed["students"].admin_levels["st-1"] = "7"
    admin_client.seed["students"].admin_status["st-1"] = "overdue"

    listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments")

    assert listing.status_code == 200, listing.text
    [row] = listing.json()["enrollments"]
    assert row["level"] == "7"
    assert row["dues_status"] == "overdue"


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

    p = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={"effective_date": "2026-05-20", "reason": "temporary pause"},
    )
    assert p.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "paused"
    paused_listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert paused_listing["enrollments"] == []
    waiting = [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ]
    assert len(waiting) == 1

    res = admin_client.post(f"/api/v2/admin/enrollments/{enrollment_id}/resume")
    assert res.status_code == 204
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "active"
    resumed_listing = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert [entry["enrollment_id"] for entry in resumed_listing["enrollments"]] == [enrollment_id]
    assert [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ] == []

    p2 = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={"effective_date": "2026-05-21", "reason": "second temporary pause"},
    )
    assert p2.status_code == 204
    waiting_after_second_pause = [
        entry
        for entry in admin_client.seed["waitlist"].entries.values()
        if entry.student_id == "st-1" and entry.status == "waiting"
    ]
    assert len(waiting_after_second_pause) == 1


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
        json={
            "target_session_id": target_session_id,
            "effective_date": "2026-05-20",
            "reason": "schedule change",
        },
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
    d = admin_client.request(
        "DELETE",
        f"/api/v2/admin/enrollments/{enrollment_id}",
        json={"effective_date": "2026-05-20", "reason": "admin cleanup"},
    )
    assert d.status_code == 204
    # EnrollmentCancelled event was appended.
    new_events = admin_client.seed["outbox"].events[outbox_len_before:]
    assert any(e.name == "Enrollment.EnrollmentCancelled" for e in new_events)
