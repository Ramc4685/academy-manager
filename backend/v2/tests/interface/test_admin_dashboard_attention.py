"""Admin dashboard attention BFF tests."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverSummary,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def test_admin_dashboard_attention_empty_state(admin_client):
    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}


def test_admin_dashboard_attention_aggregates_real_signals(admin_client):
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enroll-1",
        parent_id="parent-1",
        period="2026-05",
        reason="travel",
        status="pending",
        created_at=_dt("2026-05-01T10:00:00"),
    )
    admin_client.seed["waivers"].report = AdminWaiverReport(
        summary=AdminWaiverSummary(
            total_students=5,
            signed_count=2,
            current_count=2,
            pending_count=2,
            outdated_count=1,
        ),
        rows=[],
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [
        (item["kind"], item["href"], item["count"])
        for item in body["items"]
    ] == [
        ("pause_requests", "/admin/pause-requests", 1),
        ("waivers", "/admin/waivers", 3),
    ]


def test_admin_dashboard_attention_wrong_persona_404(
    coach_on_admin_client, parent_on_admin_client
):
    assert coach_on_admin_client.get("/api/v2/admin/dashboard/attention").status_code == 404
    assert parent_on_admin_client.get("/api/v2/admin/dashboard/attention").status_code == 404
