"""``POST /admin/session-occurrences/{id}/cancel`` (issue #671)."""

from __future__ import annotations

BASE = "/api/v2/admin/session-occurrences"


def test_cancel_marks_the_date_and_reports_the_billing_outcome(admin_client):
    r = admin_client.post(
        f"{BASE}/occ-admin-1/cancel",
        json={"reason": "gym flooded"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrence"]["occurrence_id"] == "occ-admin-1"
    assert body["occurrence"]["status"] == "cancelled"
    assert body["occurrence"]["cancellation_reason"] == "gym flooded"
    assert body["occurrence"]["cancelled_at"] is not None
    assert body["billing_result"] == "credited=1,override=written"


def test_cancelled_date_is_visible_on_the_session_occurrence_list(admin_client):
    admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": "coach sick"})

    rows = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences").json()["occurrences"]
    row = next(item for item in rows if item["occurrence_id"] == "occ-admin-1")
    assert row["status"] == "cancelled"
    assert row["cancellation_reason"] == "coach sick"


def test_cancelling_twice_is_a_conflict(admin_client):
    assert (
        admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": "rain"}).status_code == 200
    )

    again = admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": "rain"})
    assert again.status_code == 409, again.text


def test_unknown_occurrence_is_404(admin_client):
    r = admin_client.post(f"{BASE}/ghost/cancel", json={"reason": "rain"})
    assert r.status_code == 404


def test_reason_is_required(admin_client):
    assert admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": ""}).status_code == 422
    assert admin_client.post(f"{BASE}/occ-admin-1/cancel", json={}).status_code == 422


def test_coach_persona_cannot_cancel_a_date(coach_on_admin_client):
    r = coach_on_admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": "rain"})
    assert r.status_code == 404


def test_parent_persona_cannot_cancel_a_date(parent_on_admin_client):
    r = parent_on_admin_client.post(f"{BASE}/occ-admin-1/cancel", json={"reason": "rain"})
    assert r.status_code == 404


def test_route_is_registered_on_the_admin_router():
    from backend.v2.interfaces.admin.router import router
    from backend.v2.tests._route_paths import iter_route_paths

    assert "/admin/session-occurrences/{occurrence_id}/cancel" in set(
        iter_route_paths(router.routes)
    )
