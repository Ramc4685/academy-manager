"""X3 (2026-09-25 audit): a caller may only change a user they outrank.

Before the fix a plain admin could ``PATCH /users/{id}`` an owner's email,
which moved the owner's Firebase login and mailed a set-password link to the
new address: an account takeover. The same admin could disable a peer admin
or a second owner.

Owner policy chosen here: a plain admin cannot change a peer admin either;
only the owner changes admin accounts. An owner may change anyone, including
another owner.

Fixture people (``tests/interface/conftest.py``): ``o-1`` owner+admin,
``a-2`` plain admin, ``coach-1`` coach, ``p-1`` parent. ``admin_only_client``
is a plain admin (``u-admin-only``); ``admin_client`` is an owner+admin
(``u-admin``).
"""

from __future__ import annotations

import pytest

from backend.v2.interfaces.admin.owner_gate import staff_rank

OUTRANKING_TARGETS = ("o-1", "a-2")


def _audit_rows(client):
    return client.use_cases.user_governance_audit.rows


@pytest.mark.parametrize("target", OUTRANKING_TARGETS)
def test_admin_cannot_change_an_owner_or_peer_admin_email(admin_only_client, target):
    editor_calls = admin_only_client.use_cases.update_admin_user._users.commands
    invites = admin_only_client.use_cases.send_login_invite.sent

    r = admin_only_client.patch(
        f"/api/v2/admin/users/{target}",
        json={"email": "attacker@example.com", "reason": "takeover"},
    )

    assert r.status_code == 403
    assert "academy owner" in r.json()["detail"]
    assert editor_calls == []  # nothing written
    assert invites == []  # and no set-password link went out
    [row] = _audit_rows(admin_only_client)
    assert row["action"] == "user.change_denied"
    assert row["target_id"] == target
    assert row["actor_id"] == "u-admin-only"
    assert row["actor_roles"] == ("admin",)
    assert row["detail"] == {"attempted": "edit:email"}


@pytest.mark.parametrize("target", OUTRANKING_TARGETS)
def test_admin_cannot_disable_an_owner_or_peer_admin(admin_only_client, target):
    r = admin_only_client.patch(
        f"/api/v2/admin/users/{target}",
        json={"status": "disabled", "reason": "lockout"},
    )
    assert r.status_code == 403
    assert admin_only_client.use_cases.update_admin_user._users.commands == []


def test_admin_cannot_rename_an_owner(admin_only_client):
    r = admin_only_client.patch(
        "/api/v2/admin/users/o-1",
        json={"display_name": "Renamed", "reason": "x"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize("target", OUTRANKING_TARGETS)
def test_admin_cannot_send_an_owner_or_peer_admin_a_password_link(admin_only_client, target):
    r = admin_only_client.post(f"/api/v2/admin/users/{target}/login-invite")
    assert r.status_code == 403
    assert admin_only_client.use_cases.send_login_invite.sent == []


@pytest.mark.parametrize("target", OUTRANKING_TARGETS)
def test_admin_cannot_change_roles_of_an_owner_or_peer_admin(admin_only_client, target):
    add = admin_only_client.post(
        f"/api/v2/admin/users/{target}/roles", json={"role": "parent", "reason": "x"}
    )
    remove = admin_only_client.delete(f"/api/v2/admin/users/{target}/roles/coach?reason=x")
    assert add.status_code == 403
    assert remove.status_code == 403


def test_admin_still_manages_coaches_and_parents(admin_only_client):
    edit = admin_only_client.patch(
        "/api/v2/admin/users/p-1",
        json={"email": "fixed@example.com", "status": "disabled", "reason": "typo"},
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["email"] == "fixed@example.com"
    [command] = admin_only_client.use_cases.update_admin_user._users.commands
    assert command.actor_roles == ("admin",)

    invite = admin_only_client.post("/api/v2/admin/users/coach-1/login-invite")
    assert invite.status_code == 200, invite.text
    actions = [row["action"] for row in _audit_rows(admin_only_client)]
    assert actions == ["user.login_invite_sent", "user.login_invite_sent"]


def test_admin_may_edit_their_own_profile(admin_only_client):
    me = admin_only_client.use_cases.update_admin_user._users.users["a-2"].model_copy(
        update={"user_id": "u-admin-only"}
    )
    admin_only_client.use_cases.update_admin_user._users.users["u-admin-only"] = me
    admin_only_client.use_cases.get_admin_user.roles["u-admin-only"] = ["admin"]
    r = admin_only_client.patch(
        "/api/v2/admin/users/u-admin-only",
        json={"display_name": "Me", "reason": "x"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Me"


def test_nobody_disables_their_own_account(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/users/u-admin",
        json={"status": "disabled", "reason": "x"},
    )
    assert r.status_code == 409


def test_owner_can_change_another_owners_email_and_status(admin_client):
    r = admin_client.patch(
        "/api/v2/admin/users/o-1",
        json={"email": "new-owner@example.com", "reason": "owner moved address"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "new-owner@example.com"
    assert r.json()["login_invite"]["status"] == "sent"
    [command] = admin_client.use_cases.update_admin_user._users.commands
    assert command.actor_roles == ("admin", "owner")
    [row] = _audit_rows(admin_client)
    assert row["action"] == "user.login_invite_sent"
    assert row["target_roles"] == ("owner", "admin")

    disabled = admin_client.patch(
        "/api/v2/admin/users/a-2", json={"status": "disabled", "reason": "left"}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"


def test_owner_can_send_an_admin_a_password_link(admin_client):
    r = admin_client.post("/api/v2/admin/users/a-2/login-invite")
    assert r.status_code == 200, r.text
    assert admin_client.use_cases.send_login_invite.sent == ["a-2"]


def test_unknown_target_is_404_not_unranked(admin_only_client):
    r = admin_only_client.patch(
        "/api/v2/admin/users/nobody", json={"email": "x@example.com", "reason": "x"}
    )
    assert r.status_code == 404


def test_rank_fails_closed_without_a_user_lookup(admin_only_client):
    admin_only_client.use_cases.get_admin_user = None
    r = admin_only_client.patch(
        "/api/v2/admin/users/p-1", json={"email": "x@example.com", "reason": "x"}
    )
    assert r.status_code == 503


@pytest.mark.parametrize(
    ("roles", "rank"),
    [
        (("owner",), 2),
        (("parent", "owner"), 2),
        (("admin", "front_desk"), 1),
        (("billing",), 0),
        (("front_desk",), 0),
        (("coach", "parent"), 0),
        ((), 0),
    ],
)
def test_staff_rank(roles, rank):
    assert staff_rank(roles) == rank
