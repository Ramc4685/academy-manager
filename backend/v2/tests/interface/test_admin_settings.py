"""Admin Settings BFF contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.billing.domain.errors import (
    ConnectOnboardingFailed,
    UnsupportedConnectAccountRegion,
)
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
        "email_sender_name": None,
        "email_reply_to": None,
        "invoice_prefix": None,
        "sport": "badminton",
    }
    admin_client.use_cases.get_academy_use_case.execute.assert_awaited_once_with("acad")


def test_get_academy_shows_stored_sport(admin_client):
    admin_client.use_cases.get_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad", display_name="Ace Tennis", timezone=None, sport="tennis"
    )

    r = admin_client.get("/api/v2/admin/academy")

    assert r.status_code == 200, r.text
    assert r.json()["sport"] == "tennis"


def test_get_academy_shows_the_platform_set_invoice_prefix(admin_client, monkeypatch):
    # Read-only for the academy: set by the platform (Settings overhaul P1 PR 2).
    admin_client.use_cases.get_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad", display_name="Court 7", timezone=None
    )
    prefix_reader = AsyncMock()
    prefix_reader.execute.return_value = "BLNO"
    monkeypatch.setattr(admin_client.use_cases, "get_invoice_prefix", prefix_reader)

    r = admin_client.get("/api/v2/admin/academy")

    assert r.status_code == 200, r.text
    assert r.json()["invoice_prefix"] == "BLNO"
    prefix_reader.execute.assert_awaited_once_with()


def test_patch_academy_cannot_set_the_invoice_prefix(admin_client):
    admin_client.use_cases.update_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad", display_name="Court 7", timezone=None
    )

    r = admin_client.patch("/api/v2/admin/academy", json={"invoice_prefix": "EVIL"})

    assert r.status_code == 200, r.text
    admin_client.use_cases.update_academy_use_case.execute.assert_awaited_once_with("acad", {})


def test_patch_academy_cannot_set_sport(admin_client):
    # Read-only: set by the platform at bootstrap (row 13).
    admin_client.use_cases.update_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad", display_name="Court 7", timezone=None, sport="badminton"
    )

    r = admin_client.patch("/api/v2/admin/academy", json={"sport": "tennis"})

    assert r.status_code == 200, r.text
    admin_client.use_cases.update_academy_use_case.execute.assert_awaited_once_with("acad", {})
    assert r.json()["sport"] == "badminton"


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


def test_patch_academy_sender_identity_is_validated_and_normalised(admin_client):
    """L9a: sender name + reply-to are stored trimmed; blank clears."""
    admin_client.use_cases.update_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad",
        display_name="Court 7",
        timezone="UTC",
        email_sender_name="Court 7 Front Desk",
        email_reply_to="desk@example.com",
    )

    r = admin_client.patch(
        "/api/v2/admin/academy",
        json={"email_sender_name": "  Court 7 Front Desk ", "email_reply_to": "desk@example.com"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["email_sender_name"] == "Court 7 Front Desk"
    assert r.json()["email_reply_to"] == "desk@example.com"
    admin_client.use_cases.update_academy_use_case.execute.assert_awaited_once_with(
        "acad", {"email_sender_name": "Court 7 Front Desk", "email_reply_to": "desk@example.com"}
    )

    admin_client.use_cases.update_academy_use_case.execute.reset_mock()
    r = admin_client.patch(
        "/api/v2/admin/academy", json={"email_sender_name": "   ", "email_reply_to": ""}
    )
    assert r.status_code == 200, r.text
    admin_client.use_cases.update_academy_use_case.execute.assert_awaited_once_with(
        "acad", {"email_sender_name": None, "email_reply_to": None}
    )


@pytest.mark.parametrize(
    "body",
    [
        {"email_sender_name": "Court 7\r\nBcc: attacker@example.com"},
        {"email_sender_name": "Court 7\nX-Injected: 1"},
        {"email_sender_name": "Court 7 <attacker@example.com>"},
        {"email_sender_name": "x" * 81},
        {"email_reply_to": "not-an-email"},
        {"email_reply_to": "desk@example.com\r\nBcc: attacker@example.com"},
    ],
)
def test_patch_academy_rejects_unsafe_sender_identity(admin_client, body):
    r = admin_client.patch("/api/v2/admin/academy", json=body)

    assert r.status_code == 422, r.text
    admin_client.use_cases.update_academy_use_case.execute.assert_not_awaited()


def test_patch_academy_sender_identity_requires_admin(coach_on_admin_client):
    r = coach_on_admin_client.patch("/api/v2/admin/academy", json={"email_sender_name": "Court 7"})

    # Admin routes answer non-admin personas with 404 (not 403) by design.
    assert r.status_code == 404, r.text


def test_get_and_patch_fees_contract(admin_client):
    admin_client.use_cases.get_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput(
        late_fee_cents=1500,
        grace_days=5,
    )
    admin_client.use_cases.update_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput(
        late_fee_cents=2000, grace_days=5
    )

    get_response = admin_client.get("/api/v2/admin/academy/fees")
    patch_response = admin_client.patch("/api/v2/admin/academy/fees", json={"late_fee_cents": 2000})

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == {
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
            daily_digest_to_admin=True,
        )
    )
    admin_client.use_cases.update_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
            daily_digest_to_admin=True,
        )
    )

    get_response = admin_client.get("/api/v2/admin/academy/notifications")
    patch_response = admin_client.patch(
        "/api/v2/admin/academy/notifications", json={"daily_digest_to_admin": True}
    )

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == {
        "daily_digest_to_admin": True,
        # New per-academy coach-digest fields default off / hour 6.
        "coach_digest_enabled": False,
        "coach_digest_hour": 6,
        # New per-academy parent-digest fields default off / hour 6.
        "parent_digest_enabled": False,
        "parent_digest_hour": 6,
        # Row 10: win-back emails default on (unchanged for BLNO).
        "win_back_enabled": True,
    }
    assert patch_response.status_code == 200, patch_response.text
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_awaited_once_with(
        "acad", {"daily_digest_to_admin": True}
    )


def test_get_notifications_includes_coach_digest_override(admin_client):
    admin_client.use_cases.get_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(
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


def test_patch_notifications_passes_win_back_switch(admin_client):
    admin_client.use_cases.update_academy_notifications_use_case.execute.return_value = (
        GetAcademyNotificationsOutput(win_back_enabled=False)
    )

    response = admin_client.patch(
        "/api/v2/admin/academy/notifications", json={"win_back_enabled": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["win_back_enabled"] is False
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_awaited_once_with(
        "acad", {"win_back_enabled": False}
    )


def test_patch_notifications_rejects_non_boolean_win_back(admin_client):
    response = admin_client.patch(
        "/api/v2/admin/academy/notifications", json={"win_back_enabled": "sometimes"}
    )

    assert response.status_code == 422
    admin_client.use_cases.update_academy_notifications_use_case.execute.assert_not_awaited()


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


def test_start_stripe_connect_returns_clean_provider_error(admin_client):
    admin_client.use_cases.start_connect_onboarding_use_case = SimpleNamespace(
        start=AsyncMock(
            side_effect=ConnectOnboardingFailed(
                "Stripe Connect onboarding is temporarily unavailable."
            )
        )
    )

    response = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")

    assert response.status_code == 502, response.text
    assert response.json() == {
        "error": {
            "code": "Billing.ConnectOnboardingFailed",
            "message": "Stripe Connect onboarding is temporarily unavailable.",
            "details": {},
        }
    }


def test_start_stripe_connect_refuses_unsupported_region_with_409(admin_client):
    message = (
        "Stripe accounts can only be created for academies in the US billing in USD "
        "today (academy has country=CA, currency=CAD)"
    )
    admin_client.use_cases.start_connect_onboarding_use_case = SimpleNamespace(
        start=AsyncMock(side_effect=UnsupportedConnectAccountRegion(message))
    )

    response = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")

    assert response.status_code == 409, response.text
    assert response.json() == {
        "error": {
            "code": "Billing.UnsupportedConnectAccountRegion",
            "message": message,
            "details": {},
        }
    }


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


# --- Row 9: Connect return links land on the academy's own host ---------------

_BLNO_HOST = "https://blno-academy.courtmastr.com"


def _per_academy_base_url(seen: list[str]):
    async def base_url(academy_id: str) -> str:
        seen.append(academy_id)
        return _BLNO_HOST if academy_id == "acad_blno_badminton" else "https://x.courtmastr.com"

    return base_url


def test_start_stripe_connect_returns_to_the_academy_host(admin_client):
    seen: list[str] = []
    admin_client.use_cases.academy_frontend_base_url = _per_academy_base_url(seen)
    admin_client.use_cases.start_connect_onboarding_use_case = SimpleNamespace(
        start=AsyncMock(return_value={"onboarding_url": "https://connect.stripe.com/setup/a"})
    )

    # A spoofed Host header must not steer the return link anywhere.
    response = admin_client.post(
        "/api/v2/admin/academy/gateway/stripe/connect-link",
        headers={"Host": "evil.example.com", "X-Forwarded-Host": "evil.example.com"},
    )

    assert response.status_code == 200, response.text
    kwargs = admin_client.use_cases.start_connect_onboarding_use_case.start.await_args.kwargs
    # The claims' academy (fixture "acad"), never a request-supplied one.
    assert seen == ["acad"]
    assert kwargs["return_url"] == (
        "https://x.courtmastr.com/admin/settings?panel=gateway&stripe=connected"
    )
    assert (
        kwargs["refresh_url"]
        == "https://x.courtmastr.com/admin/settings?panel=gateway&stripe=error"
    )
    assert "evil" not in kwargs["return_url"] + kwargs["refresh_url"]


def test_stripe_connect_callback_redirects_to_the_verified_academy_host(admin_client):
    seen: list[str] = []
    admin_client.use_cases.academy_frontend_base_url = _per_academy_base_url(seen)
    admin_client.use_cases.complete_stripe_connect_use_case = SimpleNamespace(
        execute=AsyncMock(return_value="acad_blno_badminton")
    )

    response = admin_client.get(
        "/api/v2/admin/academy/gateway/stripe/callback?code=c&state=signed",
        headers={"Host": "evil.example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"{_BLNO_HOST}/admin/settings?panel=gateway&stripe=connected"
    )
    # The academy comes from the HMAC-verified state, not from the request.
    assert seen == ["acad_blno_badminton"]


def test_stripe_connect_callback_error_stays_on_the_platform_host(admin_client, monkeypatch):
    seen: list[str] = []
    admin_client.use_cases.academy_frontend_base_url = _per_academy_base_url(seen)
    admin_client.use_cases.complete_stripe_connect_use_case = SimpleNamespace(
        execute=AsyncMock(side_effect=ValueError("bad state"))
    )

    response = admin_client.get(
        "/api/v2/admin/academy/gateway/stripe/callback?code=c&state=forged",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith("/admin/settings?panel=gateway&stripe=error")
    assert seen == []
