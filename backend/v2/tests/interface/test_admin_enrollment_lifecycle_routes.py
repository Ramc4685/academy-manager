from __future__ import annotations


def test_pause_route_rejects_missing_resume_or_review_date(admin_client):
    created = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = created.json()["enrollment_id"]

    response = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={
            "effective_date": "2026-05-25",
            "reason": "Medical pause",
        },
    )

    assert response.status_code == 422


def test_pause_route_requires_review_date_and_records_default_policy(admin_client):
    created = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = created.json()["enrollment_id"]

    response = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/pause",
        json={
            "effective_date": "2026-05-25",
            "review_on": "2026-06-15",
            "reason": "Medical pause",
        },
    )

    assert response.status_code == 204, response.text
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "paused"
    assert admin_client.seed["sessions"].reserved["sess-1"] == 0
    waitlist_entries = list(admin_client.seed["waitlist"].entries.values())
    assert len(waitlist_entries) == 1
    assert waitlist_entries[0].student_id == "st-1"
    event = admin_client.seed["enrollment_events"].rows[-1]
    assert event.event_type == "paused"
    assert event.effective_at.date().isoformat() == "2026-05-25"
    assert event.reason == "Medical pause"
    assert event.billing_policy == "release_seat_waitlist_stop_billing"


def test_move_route_accepts_effective_date_and_returns_proration_result(admin_client):
    target = admin_client.post(
        "/api/v2/admin/sessions",
        json={
            "coach_id": "coach-2",
            "title": "Adult B",
            "location": "Court 2",
            "start_at": "2026-05-17T09:00:00Z",
            "end_at": "2026-05-17T10:30:00Z",
            "capacity": 6,
        },
    ).json()["session_id"]
    created = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = created.json()["enrollment_id"]

    response = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/transfer",
        json={
            "target_session_id": target,
            "effective_date": "2026-05-25",
            "reason": "Schedule change",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == target
    event = admin_client.seed["enrollment_events"].rows[-1]
    assert event.event_type == "moved"
    assert event.effective_at.date().isoformat() == "2026-05-25"
    assert event.billing_policy == "move_proration"
    assert event.billing_result == "recorded"


def test_withdraw_route_defaults_to_credit_and_accepts_refund_or_adjustment(admin_client):
    created = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = created.json()["enrollment_id"]

    response = admin_client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/withdraw",
        json={
            "effective_date": "2026-05-25",
            "reason": "Moving away",
            "outcome": "refund",
        },
    )

    assert response.status_code == 204, response.text
    assert admin_client.seed["enrollments"].rows[enrollment_id].status == "withdrawn"
    event = admin_client.seed["enrollment_events"].rows[-1]
    assert event.event_type == "withdrawn"
    assert event.effective_at.date().isoformat() == "2026-05-25"
    assert event.metadata["outcome"] == "refund"
    assert event.billing_policy == "withdrawal_refund"


def test_remove_route_requires_reason_and_records_actor(admin_client):
    created = admin_client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    enrollment_id = created.json()["enrollment_id"]

    missing_reason = admin_client.request(
        "DELETE",
        f"/api/v2/admin/enrollments/{enrollment_id}",
        json={"effective_date": "2026-05-25"},
    )
    assert missing_reason.status_code == 422

    removed = admin_client.request(
        "DELETE",
        f"/api/v2/admin/enrollments/{enrollment_id}",
        json={
            "effective_date": "2026-05-25",
            "reason": "Duplicate enrollment",
        },
    )
    assert removed.status_code == 204, removed.text
    event = admin_client.seed["enrollment_events"].rows[-1]
    assert event.event_type == "removed"
    assert event.reason == "Duplicate enrollment"
    assert event.actor_id == "u-admin"
