"""Admin pause request route tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import PauseRequest


def _dt() -> datetime:
    return datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def test_admin_pause_requests_include_pause_kind_and_resume_on(admin_client) -> None:
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="fixed",
        resume_on=date(2026, 7, 15),
        reason="summer",
        created_at=_dt(),
    )

    response = admin_client.get("/api/v2/admin/pause-requests")

    assert response.status_code == 200, response.text
    [request] = response.json()["requests"]
    assert request["pause_kind"] == "fixed"
    assert request["resume_on"] == "2026-07-15"


def test_admin_approve_pause_request_response_includes_new_fields(admin_client) -> None:
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="indefinite",
        reason="medical",
        created_at=_dt(),
    )

    response = admin_client.post("/api/v2/admin/pause-requests/pause-1/approve")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["pause_kind"] == "indefinite"
    assert body["resume_on"] is None


def test_dashboard_attention_includes_blocked_scheduled_resume(admin_client) -> None:
    class _Action:
        enrollment_id = "enr-1"

    async def list_blocked():
        return [_Action()]

    admin_client.use_cases.list_blocked_scheduled_resume_actions = list_blocked

    response = admin_client.get("/api/v2/admin/dashboard/attention")

    assert response.status_code == 200, response.text
    assert any(
        item["kind"] == "scheduled_resume_blocked"
        and item["href"] == "/admin/pause-requests"
        and item["count"] == 1
        for item in response.json()["items"]
    )
