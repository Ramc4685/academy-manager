"""Admin registration review route tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationDetail,
    AdminRegistrationRow,
)


def _row() -> AdminRegistrationRow:
    return AdminRegistrationRow(
        application_id="app-1",
        status="PENDING_APPROVAL",
        parent_email="parent@example.com",
        parent_name="Pat Parent",
        student_name="Sam Student",
        selected_session_id="sess-1",
        waiver_required=True,
        waiver_satisfied=True,
        updated_at=datetime(2026, 5, 24, tzinfo=UTC),
    )


def _detail(status: str = "PENDING_APPROVAL") -> AdminRegistrationDetail:
    return AdminRegistrationDetail(
        **_row().model_copy(update={"status": status}).model_dump(),
        parent_user_id="parent-1",
        child_first_name="Sam",
        child_last_name="Student",
        child_skill_level="beginner",
        payment_id="pay-1",
        session_title="Junior A",
        session_capacity=8,
        waiver_template_id="tmpl-1",
        waiver_title="Standard waiver",
        waiver_version="2026.1",
    )


def test_admin_lists_pending_registrations(admin_client) -> None:
    admin_client.use_cases.admin_registration_review.list_pending = AsyncMock(return_value=[_row()])

    response = admin_client.get("/api/v2/admin/registrations")

    assert response.status_code == 200, response.text
    assert response.json()["registrations"] == [
        {
            "application_id": "app-1",
            "status": "PENDING_APPROVAL",
            "parent_email": "parent@example.com",
            "parent_name": "Pat Parent",
            "student_name": "Sam Student",
            "selected_session_id": "sess-1",
            "waiver_required": True,
            "waiver_satisfied": True,
            "updated_at": "2026-05-24T00:00:00Z",
        }
    ]


def test_admin_approves_registration_with_actor(admin_client) -> None:
    admin_client.use_cases.admin_registration_review.approve = AsyncMock(
        return_value=_detail("APPROVED")
    )

    response = admin_client.post(
        "/api/v2/admin/registrations/app-1/approve",
        json={"session_id": "sess-1", "waiver_override_reason": "signed offline"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    command = admin_client.use_cases.admin_registration_review.approve.await_args.args[0]
    assert command.application_id == "app-1"
    assert command.actor_id == "u-admin"
    assert command.session_id == "sess-1"
    assert command.waiver_override_reason == "signed offline"


def test_admin_can_waitlist_or_reject_registration(admin_client) -> None:
    admin_client.use_cases.admin_registration_review.waitlist = AsyncMock(
        return_value=_detail("WAITLISTED")
    )
    admin_client.use_cases.admin_registration_review.reject = AsyncMock(
        return_value=_detail("DECLINED")
    )

    waitlisted = admin_client.post(
        "/api/v2/admin/registrations/app-1/waitlist",
        json={"session_id": "sess-1", "reason": "class full"},
    )
    rejected = admin_client.post(
        "/api/v2/admin/registrations/app-1/reject",
        json={"reason": "not eligible"},
    )

    assert waitlisted.status_code == 200, waitlisted.text
    assert waitlisted.json()["status"] == "WAITLISTED"
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "DECLINED"


def test_admin_reject_registration_requires_reason(admin_client) -> None:
    admin_client.use_cases.admin_registration_review.reject = AsyncMock(
        return_value=_detail("DECLINED")
    )

    response = admin_client.post(
        "/api/v2/admin/registrations/app-1/reject",
        json={"reason": ""},
    )

    assert response.status_code == 422, response.text
    admin_client.use_cases.admin_registration_review.reject.assert_not_awaited()
