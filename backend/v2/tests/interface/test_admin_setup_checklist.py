"""Admin setup checklist BFF (roadmap L7): derived completion, no data model."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.v2.contexts.identity.application.get_academy_fees_use_case import (
    GetAcademyFeesOutput,
)
from backend.v2.contexts.identity.application.get_academy_gateway_use_case import (
    GetAcademyGatewayOutput,
)
from backend.v2.contexts.identity.application.get_academy_use_case import GetAcademyOutput
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)
from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    DEFAULT_WAIVER_BODY,
)
from backend.v2.interfaces.admin.setup_checklist_routes import build_setup_checklist

URL = "/api/v2/admin/setup-checklist"


def _fresh_academy(client) -> None:
    """A just-bootstrapped academy: nothing configured yet."""
    uc = client.use_cases
    uc.get_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad", display_name="Synthetic Shuttle Club", timezone=None
    )
    uc.get_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput()
    uc.get_academy_gateway_use_case.execute.return_value = GetAcademyGatewayOutput(
        stripe_connected=False, stripe_account_id_masked=None, manual_methods=[]
    )
    uc.list_session_types = SimpleNamespace(execute=AsyncMock(return_value=[]))
    uc.list_admin_sessions = AsyncMock(return_value=[])
    uc.list_admin_users = SimpleNamespace(
        execute=AsyncMock(
            return_value=[
                AdminUserSummary(
                    user_id="owner-1",
                    email="owner@example.com",
                    display_name="Owner Synthetic",
                    role="owner",
                    status="active",
                    roles=("owner", "admin"),
                )
            ]
        )
    )
    uc.list_admin_waivers = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(active_waiver=None))
    )
    client.app.state.admin_public_page = SimpleNamespace(
        get_public_page_settings=SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(published=False))
        )
    )


def _configure_everything(client) -> None:
    uc = client.use_cases
    uc.get_academy_use_case.execute.return_value = GetAcademyOutput(
        academy_id="acad",
        display_name="Synthetic Shuttle Club",
        timezone="America/Chicago",
        contact_email="desk@example.com",
        brand_color="#1d4ed8",
    )
    uc.get_academy_fees_use_case.execute.return_value = GetAcademyFeesOutput(
        late_fee_cents=0, grace_days=5
    )
    uc.get_academy_gateway_use_case.execute.return_value = GetAcademyGatewayOutput(
        stripe_connected=True, stripe_account_id_masked="acct_...1234", manual_methods=[]
    )
    uc.list_session_types = SimpleNamespace(execute=AsyncMock(return_value=[{"id": "st-1"}]))
    uc.list_admin_sessions = AsyncMock(return_value=[{"session_id": "s-1"}])
    uc.list_admin_users.execute.return_value.append(
        AdminUserSummary(
            user_id="coach-9",
            email="coach9@example.com",
            display_name="Coach Synthetic",
            role="parent",
            status="invited",
            roles=("parent", "coach"),
        )
    )
    uc.list_admin_waivers.execute.return_value = SimpleNamespace(active_waiver=object())
    page = client.app.state.admin_public_page.get_public_page_settings
    page.execute.return_value = SimpleNamespace(published=True)


def _statuses(body: dict) -> dict[str, str]:
    return {item["key"]: item["status"] for item in body["items"]}


def test_fresh_academy_shows_every_step_todo(admin_client):
    _fresh_academy(admin_client)

    r = admin_client.get(URL)

    assert r.status_code == 200, r.text
    body = r.json()
    assert list(_statuses(body)) == [
        "academy_profile",
        "branding",
        "billing_rules",
        "stripe_connect",
        "session_types",
        "classes",
        "staff",
        "waiver",
        "public_page",
    ]
    assert set(_statuses(body).values()) == {"todo"}
    assert body["done_count"] == 0
    assert body["total"] == 9
    assert body["complete"] is False
    owner_only = {item["key"] for item in body["items"] if item["owner_only"]}
    assert owner_only == {"billing_rules", "stripe_connect"}
    # Tenant comes from the request claims, never a default academy.
    admin_client.use_cases.get_academy_use_case.execute.assert_awaited_with("acad")
    admin_client.use_cases.list_admin_users.execute.assert_awaited_once_with(
        None, academy_id="acad", exclude_role="parent"
    )


def test_configured_academy_is_complete(admin_client):
    _fresh_academy(admin_client)
    _configure_everything(admin_client)

    r = admin_client.get(URL)

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(_statuses(body).values()) == {"done"}, body
    assert body["done_count"] == 9
    assert body["complete"] is True


def test_one_failing_source_reports_unknown_not_500(admin_client):
    _fresh_academy(admin_client)
    admin_client.use_cases.get_academy_gateway_use_case.execute.side_effect = RuntimeError(
        "stripe lookup failed"
    )
    del admin_client.app.state.admin_public_page

    r = admin_client.get(URL)

    assert r.status_code == 200, r.text
    statuses = _statuses(r.json())
    assert statuses["stripe_connect"] == "unknown"
    assert statuses["public_page"] == "unknown"
    assert statuses["branding"] == "todo"


def test_admin_without_owner_scope_can_read_the_checklist(admin_only_client):
    _fresh_academy(admin_only_client)

    r = admin_only_client.get(URL)

    assert r.status_code == 200, r.text
    # Status only: no amounts, no account ids, nothing money-moving.
    for item in r.json()["items"]:
        assert set(item) == {"key", "label", "detail", "status", "href", "owner_only"}


def test_wrong_persona_gets_404(coach_on_admin_client, parent_on_admin_client):
    assert coach_on_admin_client.get(URL).status_code == 404
    assert parent_on_admin_client.get(URL).status_code == 404


def _derive(**overrides):
    sources = {
        "academy": (True, None),
        "fees": (True, None),
        "gateway": (True, None),
        "session_types": (True, []),
        "classes": (True, []),
        "users": (True, []),
        "waivers": (True, None),
        "public_page": (True, None),
    }
    sources.update(overrides)
    view = build_setup_checklist(**sources)
    return {item.key: item.status for item in view.items}


def test_zero_late_fee_is_a_choice_but_unset_grace_is_not():
    assert _derive(fees=(True, {"late_fee_cents": 0, "grace_days": 0}))["billing_rules"] == "done"
    assert _derive(fees=(True, {"late_fee_cents": 500, "grace_days": None}))["billing_rules"] == (
        "todo"
    )


def test_parent_only_accounts_do_not_count_as_staff():
    owner = {"role": "owner", "roles": ["owner"]}
    parent = {"role": "parent", "roles": ["parent"]}
    front_desk = {"role": "front_desk", "roles": ["front_desk"]}
    assert _derive(users=(True, [owner, parent, parent]))["staff"] == "todo"
    assert _derive(users=(True, [owner, front_desk]))["staff"] == "done"


def test_roles_array_is_authoritative_and_inactive_staff_do_not_count():
    owner = {"role": "owner", "roles": ["owner"], "status": "active"}
    # ``role`` is derived as ``roles[0]``; a stray scalar never adds a role.
    stale = {"role": "coach", "roles": ["parent"], "status": "active"}
    legacy_coach = {"role": "coach", "roles": [], "status": "active"}
    disabled_coach = {"role": "coach", "roles": ["coach"], "status": "disabled"}
    assert _derive(users=(True, [owner, stale]))["staff"] == "todo"
    assert _derive(users=(True, [owner, disabled_coach]))["staff"] == "todo"
    assert _derive(users=(True, [owner, legacy_coach]))["staff"] == "done"


def test_blank_strings_do_not_count_as_set():
    academy = {"timezone": "  ", "contact_email": "desk@example.com", "logo_url": ""}
    statuses = _derive(academy=(True, academy))
    assert statuses["academy_profile"] == "todo"
    assert statuses["branding"] == "todo"


def test_bootstrap_placeholder_waiver_is_not_done():
    placeholder = {"active_waiver": {"body": DEFAULT_WAIVER_BODY}}
    own = {"active_waiver": {"body": "Synthetic academy waiver text."}}
    assert _derive(waivers=(True, placeholder))["waiver"] == "todo"
    assert _derive(waivers=(True, own))["waiver"] == "done"
    assert _derive(waivers=(True, {"active_waiver": None}))["waiver"] == "todo"


def test_unavailable_source_is_unknown():
    assert _derive(classes=(False, None))["classes"] == "unknown"
