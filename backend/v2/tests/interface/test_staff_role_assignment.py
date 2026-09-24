"""Staff page role assignment (#553, roadmap L2c): who may grant what.

The Staff page (``/admin/users``) assigns owner, admin, billing, front desk
and coach through the directory role routes. The permission matrix, per
caller:

* owner: every role, grant and revoke;
* admin without owner: coach, assistant coach and parent only. Admin, owner,
  billing and front desk answer 403 with a message the UI shows;
* billing, front desk, coach, parent: not admin personas, so 404 before any
  role rule runs.

The academy can never lose its last owner (409), which the store enforces and
the in-memory fake mirrors.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.v2.tests.interface.conftest import (  # type: ignore[attr-defined]
    _build_admin_use_cases,
    _claims,
    _make_admin_app,
)

#: An academy owner as the admin surface sees one: ``_claims("admin")`` holds
#: admin + owner, what migration 0165 left every pre-split admin with.
OWNER = "admin"

GOVERNANCE = ("admin", "owner", "billing", "front_desk")
OPERATIONS = ("coach", "assistant_coach", "parent")


@pytest.fixture
def client_for(admin_seed) -> Iterator:
    clients: list[TestClient] = []

    def _make(role: str) -> TestClient:
        client = TestClient(_make_admin_app(_claims(role), _build_admin_use_cases(admin_seed)))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("role", [*GOVERNANCE, *OPERATIONS])
def test_owner_grants_every_staff_role(client_for, role: str) -> None:
    r = client_for(OWNER).post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "Staff change"}
    )
    assert r.status_code == 200, r.text
    assert role in r.json()["roles"]


@pytest.mark.parametrize("role", ["billing", "front_desk", "admin"])
def test_owner_revokes_a_staff_tier(client_for, role: str) -> None:
    client = client_for(OWNER)
    granted = client.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "Staff change"}
    )
    assert granted.status_code == 200, granted.text

    r = client.delete(f"/api/v2/admin/users/coach-1/roles/{role}?reason=Moved%20on")

    assert r.status_code == 200, r.text
    assert role not in r.json()["roles"]


@pytest.mark.parametrize("role", GOVERNANCE)
def test_admin_without_owner_cannot_grant_governance_roles(client_for, role: str) -> None:
    r = client_for("admin-only").post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "promotion"}
    )
    assert r.status_code == 403
    assert "academy owner" in r.json()["detail"]


@pytest.mark.parametrize("role", ["billing", "front_desk"])
def test_admin_without_owner_cannot_revoke_a_staff_tier(client_for, role: str) -> None:
    r = client_for("admin-only").delete(f"/api/v2/admin/users/coach-1/roles/{role}?reason=x")
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["billing", "front_desk"])
def test_admin_without_owner_cannot_create_a_staff_tier_user(client_for, role: str) -> None:
    r = client_for("admin-only").post(
        "/api/v2/admin/users",
        json={
            "role": role,
            "display_name": "Test Staff",
            "email": "test-staff@example.com",
            "reason": "hire",
        },
    )
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["billing", "front_desk"])
def test_admin_without_owner_cannot_replace_a_role_with_a_staff_tier(client_for, role: str) -> None:
    r = client_for("admin-only").patch(
        "/api/v2/admin/users/coach-1/role", json={"role": role, "reason": "promotion"}
    )
    assert r.status_code == 403


@pytest.mark.parametrize("role", OPERATIONS)
def test_admin_without_owner_still_grants_operations_roles(client_for, role: str) -> None:
    r = client_for("admin-only").post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "Staff change"}
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("caller", ["billing", "front_desk", "coach", "parent"])
@pytest.mark.parametrize("role", ["billing", "front_desk", "coach"])
def test_non_admin_callers_never_reach_role_management(client_for, caller: str, role: str) -> None:
    client = client_for(caller)
    grant = client.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "Staff change"}
    )
    revoke = client.delete(f"/api/v2/admin/users/coach-1/roles/{role}?reason=x")
    assert grant.status_code == 404
    assert revoke.status_code == 404


def test_removing_the_last_owner_is_a_409(client_for) -> None:
    # In the fake directory o-1 is the academy's only owner.
    r = client_for(OWNER).delete("/api/v2/admin/users/o-1/roles/owner?reason=x")

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Identity.CannotRemoveLastOwner"


def test_an_owner_can_be_removed_once_there_is_a_second_owner(client_for) -> None:
    client = client_for(OWNER)
    granted = client.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": "owner", "reason": "co-owner"}
    )
    assert granted.status_code == 200, granted.text

    r = client.delete("/api/v2/admin/users/o-1/roles/owner?reason=Stepped%20back")

    assert r.status_code == 200, r.text
    assert "owner" not in r.json()["roles"]
