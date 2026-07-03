"""Admin Settings BFF contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.v2.contexts.identity.application.change_user_role_use_case import (
    ChangeUserRoleCommand,
)
from backend.v2.contexts.identity.application.get_academy_fees_use_case import (
    GetAcademyFeesOutput,
)
from backend.v2.contexts.identity.application.get_academy_gateway_use_case import (
    GetAcademyGatewayOutput,
)
from backend.v2.contexts.identity.application.get_academy_notifications_use_case import (
    GetAcademyNotificationsOutput,
)
from backend.v2.contexts.identity.application.get_academy_use_case import GetAcademyOutput
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)


def test_get_academy_contract(admin_client):
    admin_client.use_cases.get_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad",
        display_name="Court 7",
        timezone="America/Chicago",
        contact_email="ops@example.com",
        logo_url="https://cdn.example.com/logo.png",
        brand_color="#2563eb",
    )

    r = admin_client.get("/api/v2/admin/academy")

    assert r.status_code == 200, r.text
    assert r.json() == {
        "academy_id": "acad",
        "display_name": "Court 7",
        "timezone": "America/Chicago",
        "contact_email": "ops@example.com",
        "contact_phone": None,
        "hours_text": None,
        "address": None,
        "logo_url": "https://cdn.example.com/logo.png",
        "brand_color": "#2563eb",
        "currency": "USD",
    }
    admin_client.use_cases.get_academy_use_case.execute.assert_awaited_once_with("acad")


def test_patch_academy_contract(admin_client):
    admin_client.use_cases.update_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad",
        display_name="Court 7",
        timezone="UTC",
        brand_color="#facc15",
    )

    r = admin_client.patch(
        "/api/v2/admin/academy",
        json={"display_name": "Court 7", "brand_color": "#facc15"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["brand_color"] == "#facc15"
    admin_client.use_cases.update_academy_use_case.execute.assert_awaited_once_with(
        "acad", {"display_name": "Court 7", "brand_color": "#facc15"}
    )


def test_get_and_patch_fees_contract(admin_client):
    admin_client.use_cases.get_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput(
        default_monthly_cents=12000,
        late_fee_cents=1500,
        grace_days=5,
    )
    admin_client.use_cases.update_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput(
        default_monthly_cents=12000, late_fee_cents=2000, grace_days=5
    )

    get_response = admin_client.get("/api/v2/admin/academy/fees")
    patch_response = admin_client.patch("/api/v2/admin/academy/fees", json={"late_fee_cents": 2000})

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == {
        "default_monthly_cents": 12000,
        "late_fee_cents": 1500,
        "grace_days": 5,
    }
    assert patch_response.status_code == 200, patch_response.text
    admin_client.use_cases.update_academy_fees_use_case.execute.assert_awaited_once_with(
        "acad", {"late_fee_cents": 2000}
    )


def test_get_and_patch_notifications_contract(admin_client):
    admin_client.use_cases.get_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
            dues_reminders=True,
            attendance_alerts=False,
            daily_digest_to_admin=True,
        )
    )
    admin_client.use_cases.update_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
            dues_reminders=True,
            attendance_alerts=True,
            daily_digest_to_admin=True,
        )
    )

    get_response = admin_client.get("/api/v2/admin/academy/notifications")
    patch_response = admin_client.patch(
        "/api/v2/admin/academy/notifications", json={"attendance_alerts": True}
    )

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == {
        "dues_reminders": True,
        "attendance_alerts": False,
        "daily_digest_to_admin": True,
        # New per-academy coach-digest fields default off / hour 6.
        "coach_digest_enabled": False,
        "coach_digest_hour": 6,
    }
    assert patch_response.status_code == 200, patch_response.text
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_awaited_once_with(
        "acad", {"attendance_alerts": True}
    )


def test_get_notifications_includes_coach_digest_override(admin_client):
    admin_client.use_cases.get_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
            dues_reminders=False,
            attendance_alerts=False,
            daily_digest_to_admin=False,
            coach_digest_enabled=True,
            coach_digest_hour=18,
        )
    )

    response = admin_client.get("/api/v2/admin/academy/notifications")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coach_digest_enabled"] is True
    assert body["coach_digest_hour"] == 18


def test_patch_notifications_passes_coach_digest_fields(admin_client):
    admin_client.use_cases.update_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
            coach_digest_enabled=True,
            coach_digest_hour=7,
        )
    )

    response = admin_client.patch(
        "/api/v2/admin/academy/notifications",
        json={"coach_digest_enabled": True, "coach_digest_hour": 7},
    )

    assert response.status_code == 200, response.text
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_awaited_once_with(
        "acad", {"coach_digest_enabled": True, "coach_digest_hour": 7}
    )


def test_patch_notifications_rejects_out_of_range_hour(admin_client):
    response = admin_client.patch(
        "/api/v2/admin/academy/notifications",
        json={"coach_digest_hour": 24},
    )

    assert response.status_code == 422, response.text
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_not_awaited()


def test_get_gateway_contract(admin_client):
    admin_client.use_cases.get_academy_gateway_use_case.execute.return_value = (
        GetAcademyGatewayOutput(
            stripe_connected=True,
            stripe_account_id_masked="acct...1234",
            manual_methods=["cash", "check"],
        )
    )

    response = admin_client.get("/api/v2/admin/academy/gateway")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "stripe_connected": True,
        "stripe_account_id_masked": "acct...1234",
        "manual_methods": ["cash", "check"],
    }
    admin_client.use_cases.get_academy_gateway_use_case.execute.assert_awaited_once_with("acad")


def test_start_stripe_connect_returns_clear_error_when_not_configured(admin_client):
    admin_client.use_cases.start_connect_onboarding_use_case = None

    response = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")

    assert response.status_code == 503, response.text
    assert response.json() == {
        "detail": "Online payouts are not set up yet. Finish payment setup in academy settings."
    }


def test_start_stripe_connect_returns_onboarding_url(admin_client):
    admin_client.use_cases.start_connect_onboarding_use_case = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "academy_id": "acad",
                "stripe_account_id": "acct_123",
                "onboarding_url": "https://connect.stripe.com/setup/acct_123",
                "status": "pending",
            }
        )
    )

    response = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://connect.stripe.com/setup/acct_123"}
    call = admin_client.use_cases.start_connect_onboarding_use_case.start
    call.assert_awaited_once()
    assert call.await_args.kwargs["academy_id"] == "acad"
    assert "panel=gateway&stripe=connected" in call.await_args.kwargs["return_url"]
    assert "panel=gateway&stripe=error" in call.await_args.kwargs["refresh_url"]


def test_patch_user_role_contract(admin_client):
    admin_client.use_cases.change_user_role.execute.return_value = AdminUserSummary(
        user_id="coach-1",
        email="coach@example.com",
        display_name="Coach One",
        role="admin",
        status="active",
    )

    response = admin_client.patch("/api/v2/admin/users/coach-1/role", json={"role": "admin"})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    admin_client.use_cases.change_user_role.execute.assert_awaited_once_with(
        "coach-1",
        ChangeUserRoleCommand(
            role="admin",
            actor_id="u-admin",
            reason="admin role change",
        ),
        academy_id="acad",
    )


def test_patch_user_role_forbids_self_lockout(admin_client):
    response = admin_client.patch("/api/v2/admin/users/u-admin/role", json={"role": "coach"})

    assert response.status_code == 400, response.text
    admin_client.use_cases.change_user_role.execute.assert_not_awaited()
