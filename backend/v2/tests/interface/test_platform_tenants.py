"""Interface tests for platform tenant lifecycle routes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    TenantLifecycleService,
)
from backend.v2.interfaces.platform.bootstrap_routes import router as platform_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_tenant_lifecycle import FakeTenantRepository


def _platform_admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _platform_support_claims() -> AuthClaims:
    return AuthClaims(
        user_id="platform-support",
        email="support@example.com",
        academy_id="platform-control",
        platform_roles=("platform_support",),
    )


def _academy_admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="academy-admin",
        email="admin@example.com",
        academy_id="academy-a",
        membership_id="membership-a",
        roles=("admin",),
    )


def _app(claims: AuthClaims, repo: FakeTenantRepository) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(platform_router, prefix="/api/v2")
    app.state.tenant_lifecycle = TenantLifecycleService(
        tenants=repo,
        id_factory=lambda prefix: f"{prefix}test",
    )

    async def _override_claims() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override_claims
    return app


@pytest.fixture()
def repo() -> FakeTenantRepository:
    return FakeTenantRepository()


@pytest.fixture()
def platform_client(repo: FakeTenantRepository) -> Iterator[TestClient]:
    with TestClient(_app(_platform_admin_claims(), repo)) as client:
        yield client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": "North Shore Badminton",
        "slug": "north-shore",
        "primary_domain": "north.example.com",
        "plan_code": "starter",
        "limits": {"max_students": 100, "max_coaches": 8},
    }
    payload.update(overrides)
    return payload


def _create(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v2/platform/tenants", json=_payload())
    assert response.status_code == 200, response.text
    return response.json()


def test_platform_admin_can_create_and_drive_tenant_lifecycle(platform_client: TestClient) -> None:
    created = _create(platform_client)

    assert created["academy_id"] == "tenant_test"
    assert created["status"] == "provisioning"
    assert created["servable"] is False

    active = platform_client.post("/api/v2/platform/tenants/tenant_test/activate")
    suspended = platform_client.post(
        "/api/v2/platform/tenants/tenant_test/suspend",
        json={"reason": "payment_failed"},
    )
    reactivated = platform_client.post("/api/v2/platform/tenants/tenant_test/reactivate")
    cancelled = platform_client.post(
        "/api/v2/platform/tenants/tenant_test/cancel",
        json={"reason": "customer_request"},
    )

    assert active.status_code == 200, active.text
    assert suspended.status_code == 200, suspended.text
    assert reactivated.status_code == 200, reactivated.text
    assert cancelled.status_code == 200, cancelled.text
    assert [r.json()["status"] for r in [active, suspended, reactivated, cancelled]] == [
        "active",
        "suspended",
        "active",
        "cancelled",
    ]


def test_platform_admin_can_update_plan_limits_after_reactivation(
    platform_client: TestClient,
) -> None:
    _create(platform_client)
    assert platform_client.post("/api/v2/platform/tenants/tenant_test/activate").status_code == 200
    assert (
        platform_client.post(
            "/api/v2/platform/tenants/tenant_test/cancel",
            json={"reason": "customer_request"},
        ).status_code
        == 200
    )
    blocked = platform_client.patch(
        "/api/v2/platform/tenants/tenant_test/plan",
        json={"plan_code": "growth", "limits": {"max_students": 300, "max_coaches": 24}},
    )
    assert blocked.status_code == 409

    assert (
        platform_client.post("/api/v2/platform/tenants/tenant_test/reactivate").status_code == 200
    )
    updated = platform_client.patch(
        "/api/v2/platform/tenants/tenant_test/plan",
        json={"plan_code": "growth", "limits": {"max_students": 300, "max_coaches": 24}},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["plan_code"] == "growth"
    assert updated.json()["limits"]["max_students"] == 300


def test_tenant_health_exposes_status_check_for_request_gating(
    platform_client: TestClient,
) -> None:
    _create(platform_client)

    provisioning = platform_client.get("/api/v2/platform/tenants/tenant_test/health")
    assert provisioning.status_code == 200
    assert provisioning.json() == {
        "academy_id": "tenant_test",
        "status": "provisioning",
        "servable": False,
        "reason": "tenant_status_provisioning",
        "plan_code": "starter",
        "limits": {"max_students": 100, "max_coaches": 8, "max_locations": None},
    }

    platform_client.post("/api/v2/platform/tenants/tenant_test/activate")
    active = platform_client.get("/api/v2/platform/tenants/tenant_test/health")
    assert active.status_code == 200
    assert active.json()["servable"] is True
    assert active.json()["reason"] is None


def test_platform_support_can_read_status_but_cannot_mutate(repo: FakeTenantRepository) -> None:
    with TestClient(_app(_platform_admin_claims(), repo)) as admin_client:
        _create(admin_client)

    with TestClient(_app(_platform_support_claims(), repo)) as support_client:
        status_response = support_client.get("/api/v2/platform/tenants/tenant_test/status")
        mutate_response = support_client.post("/api/v2/platform/tenants/tenant_test/activate")

    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "provisioning"
    assert mutate_response.status_code == 404


def test_academy_roles_cannot_access_platform_lifecycle(repo: FakeTenantRepository) -> None:
    with TestClient(_app(_academy_admin_claims(), repo)) as client:
        create_response = client.post("/api/v2/platform/tenants", json=_payload())
        status_response = client.get("/api/v2/platform/tenants/tenant_test/status")

    assert create_response.status_code == 404
    assert status_response.status_code == 404
