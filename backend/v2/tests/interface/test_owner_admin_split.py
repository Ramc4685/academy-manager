"""Owner / admin split on the admin BFF.

`admin_client` is a pre-split admin (roles admin+owner, what migration 0165
leaves every existing admin with). `admin_only_client` is an admin invited
after the split: operations only. Money governance 404s for it exactly like
any other missing persona, and inside the role routes the action-level rule
403s with a message the UI can show.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)

OWNER_ONLY_GETS = (
    "/api/v2/admin/finance/revenue",
    "/api/v2/admin/audit-logs",
    "/api/v2/admin/payroll/2026-09",
)


@pytest.mark.parametrize("path", OWNER_ONLY_GETS)
def test_admin_only_gets_404_on_owner_only_reads(admin_only_client, path):
    assert admin_only_client.get(path).status_code == 404


def test_admin_only_gets_404_on_refund(admin_only_client):
    r = admin_only_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-1", "amount_cents": 100, "reason": "x"},
    )
    assert r.status_code == 404


def test_admin_only_keeps_operations_reads(admin_only_client):
    assert admin_only_client.get("/api/v2/admin/finance/expenses").status_code == 200
    assert admin_only_client.get("/api/v2/admin/payments").status_code == 200


def test_admin_only_cannot_grant_admin(admin_only_client):
    r = admin_only_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "admin", "reason": "promotion"},
    )
    assert r.status_code == 403
    assert "academy owner" in r.json()["detail"]


def test_admin_only_cannot_grant_owner(admin_only_client):
    r = admin_only_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "owner", "reason": "promotion"},
    )
    assert r.status_code == 403


def test_admin_only_cannot_create_an_admin_user(admin_only_client):
    r = admin_only_client.post(
        "/api/v2/admin/users",
        json={
            "role": "admin",
            "display_name": "New Admin",
            "email": "new-admin@example.com",
            "reason": "hire",
        },
    )
    assert r.status_code == 403


def test_admin_only_cannot_change_a_role_to_admin(admin_only_client):
    r = admin_only_client.patch(
        "/api/v2/admin/users/coach-1/role",
        json={"role": "admin", "reason": "promotion"},
    )
    assert r.status_code == 403


def test_admin_only_cannot_demote_an_owner_by_replacing_their_role(admin_only_client):
    """PATCH /role replaces every held role, so setting an owner to "parent"
    would silently revoke owner. The rule must look at held roles too."""
    r = admin_only_client.patch(
        "/api/v2/admin/users/o-1/role",
        json={"role": "parent", "reason": "demotion"},
    )
    assert r.status_code == 403


def test_admin_only_may_still_replace_a_coach_role(admin_only_client):
    # coach-1 holds no governance role; the rule must not block this.
    admin_only_client.use_cases.change_user_role.execute.return_value = AdminUserSummary(
        user_id="coach-1",
        email="coach-1@example.com",
        display_name="coach-1",
        role="parent",
        status="active",
    )
    r = admin_only_client.patch(
        "/api/v2/admin/users/coach-1/role",
        json={"role": "parent", "reason": "left coaching"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "parent"


def test_admin_only_still_grants_operations_roles(admin_only_client):
    r = admin_only_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "parent", "reason": "Coach is also a parent"},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["roles"]) == {"coach", "parent"}


def test_owner_grants_admin(admin_client):
    r = admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "admin", "reason": "promotion"},
    )
    assert r.status_code == 200, r.text
    assert "admin" in r.json()["roles"]


def test_owner_grants_owner_without_a_feature_flag(admin_client):
    """The old `enable_owner_role` 404 is gone: owner is a plain academy role."""
    r = admin_client.post(
        "/api/v2/admin/users/coach-1/roles",
        json={"role": "owner", "reason": "co-owner"},
    )
    assert r.status_code == 200, r.text
    assert "owner" in r.json()["roles"]


def test_owner_cannot_remove_own_owner_role(admin_client):
    # admin_client's claims user_id — see conftest _claims(): "u-admin"
    r = admin_client.delete("/api/v2/admin/users/u-admin/roles/owner?reason=x")
    assert r.status_code == 409


def test_owner_still_cannot_remove_own_admin_role(admin_client):
    r = admin_client.delete("/api/v2/admin/users/u-admin/roles/admin?reason=x")
    assert r.status_code == 409


def test_admin_only_cannot_revoke_admin_from_someone_else(admin_client, admin_only_client):
    admin_client.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": "admin", "reason": "setup"}
    )
    r = admin_only_client.delete("/api/v2/admin/users/coach-1/roles/admin?reason=x")
    assert r.status_code == 403
