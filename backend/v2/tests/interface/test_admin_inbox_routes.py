"""Admin unified inbox counts (issue #776).

One counted queue list behind ``GET /admin/inbox/counts`` so the Inbox page can
label every tab and default to the first queue that actually needs attention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import PauseRequest
from backend.v2.interfaces.admin.inbox_routes import INBOX_QUEUE_IDS


def _pause(pause_request_id: str, status: str = "pending") -> PauseRequest:
    return PauseRequest(
        pause_request_id=pause_request_id,
        enrollment_id="enroll-1",
        parent_id="parent-1",
        period="2026-05",
        resume_on=datetime(2026, 5, 15, tzinfo=UTC).date(),
        reason="travel",
        status=status,
        created_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
    )


def test_inbox_counts_returns_every_queue_even_when_empty(admin_client):
    admin_client.use_cases.admin_registration_review.list_pending = AsyncMock(return_value=[])

    r = admin_client.get("/api/v2/admin/inbox/counts")

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["counts"]) == set(INBOX_QUEUE_IDS)
    assert body["total"] == 0


def test_inbox_counts_returns_per_queue_pending_counts(admin_client):
    admin_client.use_cases.admin_registration_review.list_pending = AsyncMock(
        return_value=[object(), object()]
    )
    admin_client.use_cases.list_makeup_requests_for_admin = AsyncMock()
    admin_client.use_cases.list_makeup_requests_for_admin.execute = AsyncMock(
        return_value=[object()]
    )
    admin_client.seed["pause_requests"].rows["pause-1"] = _pause("pause-1")
    admin_client.seed["pause_requests"].rows["pause-2"] = _pause("pause-2", status="approved")

    r = admin_client.get("/api/v2/admin/inbox/counts")

    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["registrations"] == 2
    assert counts["makeups"] == 1
    # Only requests still waiting on a human count as inbox work.
    assert counts["pauses"] == 1
    assert r.json()["total"] == 4
    # The pending filter is the queue's, not the caller's.
    admin_client.use_cases.list_makeup_requests_for_admin.execute.assert_awaited_once_with(
        "pending"
    )


def test_inbox_counts_degrade_to_zero_when_one_queue_is_unreadable(admin_client):
    admin_client.use_cases.admin_registration_review.list_pending = AsyncMock(
        side_effect=RuntimeError("registration store down")
    )
    admin_client.seed["pause_requests"].rows["pause-1"] = _pause("pause-1")

    r = admin_client.get("/api/v2/admin/inbox/counts")

    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["registrations"] == 0
    assert counts["pauses"] == 1


def test_inbox_counts_are_admin_only(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/inbox/counts").status_code == 404
