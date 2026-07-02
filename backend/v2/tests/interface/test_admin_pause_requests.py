"""Admin pause request route tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import PauseRequest
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student


def _dt() -> datetime:
    return datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _seed_enrollment(admin_client, *, enrollment_id: str, student_id: str, parent_id: str) -> None:
    admin_client.seed["enrollments"].rows[enrollment_id] = Enrollment(
        enrollment_id=enrollment_id,
        academy_id="acad",
        session_id="session-1",
        student_id=student_id,
        status="active",
    )
    admin_client.seed["students"].students[student_id] = Student(
        student_id=student_id,
        academy_id="acad",
        parent_id=parent_id,
        full_name="Aadhya Abhishek",
    )


def test_admin_pause_requests_include_pause_kind_and_resume_on(admin_client) -> None:
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        parent_name="Abhishek Ajithkumar",
        parent_email="abhishek@example.com",
        student_id="student-1",
        student_name="Aadhya Abhishek",
        session_id="session-1",
        session_title="Junior Foundations",
        session_location="Court 2",
        session_start_at=datetime(2026, 6, 4, 23, 0, tzinfo=UTC),
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
    assert request["parent_name"] == "Abhishek Ajithkumar"
    assert request["parent_email"] == "abhishek@example.com"
    assert request["student_name"] == "Aadhya Abhishek"
    assert request["session_title"] == "Junior Foundations"
    assert request["session_location"] == "Court 2"
    assert request["session_start_at"] == "2026-06-04T23:00:00Z"


def test_admin_approve_pause_request_response_includes_new_fields(admin_client) -> None:
    _seed_enrollment(
        admin_client, enrollment_id="enr-1", student_id="student-1", parent_id="parent-1"
    )
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enr-1",
        parent_id="parent-1",
        pause_kind="indefinite",
        review_on=date(2026, 7, 1),
        reason="medical",
        created_at=_dt(),
    )

    response = admin_client.post("/api/v2/admin/pause-requests/pause-1/approve")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["pause_kind"] == "indefinite"
    assert body["resume_on"] is None
    assert body["review_on"] == "2026-07-01"


def test_admin_approve_pause_request_sets_enrollment_autopay_paused(admin_client) -> None:
    """Regression (Slice B): approving a pause request toggles THIS enrollment's
    app-owned autopay_enrollment_status to paused (per-enrollment — siblings
    unaffected). There is no Stripe subscription collection to pause any more."""
    _seed_enrollment(
        admin_client, enrollment_id="enr-2", student_id="student-2", parent_id="parent-2"
    )
    admin_client.seed["pause_requests"].rows["pause-2"] = PauseRequest(
        pause_request_id="pause-2",
        enrollment_id="enr-2",
        parent_id="parent-2",
        pause_kind="indefinite",
        review_on=date(2026, 7, 1),
        reason="medical",
        created_at=_dt(),
    )

    response = admin_client.post("/api/v2/admin/pause-requests/pause-2/approve")

    assert response.status_code == 200, response.text
    # Per-enrollment: keyed by enrollment_id, not parent_id.
    assert admin_client.seed["autopay_status"].statuses["enr-2"] == "paused"
    assert admin_client.seed["enrollments"].rows["enr-2"].status == "paused"


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
