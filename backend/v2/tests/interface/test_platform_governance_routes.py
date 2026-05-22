"""Interface tests for platform governance and support access routes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.governance.application.use_cases import (
    TenantGovernanceService,
)
from backend.v2.interfaces.platform.governance_routes import router as governance_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_tenant_governance import FakeGovernanceStore


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


def _app(claims: AuthClaims, store: FakeGovernanceStore) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(governance_router, prefix="/api/v2")
    counters: dict[str, int] = {}

    def _id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]:03d}"

    app.state.tenant_governance = TenantGovernanceService(
        store=store,
        id_factory=_id,
    )

    async def _override_claims() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override_claims
    return app


@pytest.fixture()
def store() -> FakeGovernanceStore:
    return FakeGovernanceStore()


@pytest.fixture()
def platform_client(store: FakeGovernanceStore) -> Iterator[TestClient]:
    with TestClient(_app(_platform_admin_claims(), store)) as client:
        yield client


def test_platform_admin_can_create_list_and_check_governance_request_status(
    platform_client: TestClient,
) -> None:
    export = platform_client.post(
        "/api/v2/platform/governance/tenant-exports",
        json={
            "academy_id": "acad_001",
            "reason": "owner portability request",
            "include_pii": False,
        },
        headers={"x-request-id": "req-export"},
    )
    tenant_deletion = platform_client.post(
        "/api/v2/platform/governance/tenant-deletions",
        json={"academy_id": "acad_001", "reason": "owner closure request"},
    )
    student_deletion = platform_client.post(
        "/api/v2/platform/governance/student-data-deletions",
        json={
            "academy_id": "acad_001",
            "student_id": "student_001",
            "reason": "parent erasure request",
        },
    )
    listed = platform_client.get(
        "/api/v2/platform/governance/tenant-exports",
        params={"academy_id": "acad_001"},
    )
    status = platform_client.get("/api/v2/platform/governance/requests/tenant_export_001/status")

    assert export.status_code == 200, export.text
    assert tenant_deletion.status_code == 200, tenant_deletion.text
    assert student_deletion.status_code == 200, student_deletion.text
    assert export.json()["status"] == "queued"
    assert tenant_deletion.json()["hard_delete_allowed"] is False
    assert student_deletion.json()["delete_student_profile"] is False
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["export_request_id"] == "tenant_export_001"
    assert status.status_code == 200, status.text
    assert status.json() == {
        "request_id": "tenant_export_001",
        "request_type": "tenant_export",
        "academy_id": "acad_001",
        "status": "queued",
    }


def test_platform_admin_can_grant_and_revoke_support_access(
    platform_client: TestClient,
) -> None:
    created = platform_client.post(
        "/api/v2/platform/governance/support-access-grants",
        json={
            "academy_id": "acad_001",
            "support_user_id": "user_support_002",
            "purpose": "debug tenant onboarding",
            "expires_in_hours": 2,
        },
    )
    revoked = platform_client.post(
        "/api/v2/platform/governance/support-access-grants/support_access_001/revoke",
        json={"academy_id": "acad_001", "reason": "issue resolved"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["status"] == "active"
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"


def test_platform_support_can_read_and_request_manual_impersonation(
    store: FakeGovernanceStore,
) -> None:
    with TestClient(_app(_platform_admin_claims(), store)) as admin_client:
        admin_client.post(
            "/api/v2/platform/governance/tenant-exports",
            json={"academy_id": "acad_001", "reason": "owner portability request"},
        )

    with TestClient(_app(_platform_support_claims(), store)) as support_client:
        listed = support_client.get(
            "/api/v2/platform/governance/tenant-exports",
            params={"academy_id": "acad_001"},
        )
        impersonation = support_client.post(
            "/api/v2/platform/governance/support-impersonation-requests",
            json={
                "academy_id": "acad_001",
                "target_user_id": "parent_001",
                "purpose": "reproduce parent portal issue",
            },
        )
        blocked_mutation = support_client.post(
            "/api/v2/platform/governance/tenant-deletions",
            json={"academy_id": "acad_001", "reason": "should not be allowed"},
        )

    assert listed.status_code == 200, listed.text
    assert impersonation.status_code == 200, impersonation.text
    assert impersonation.json()["status"] == "requires_manual_approval"
    assert impersonation.json()["impersonation_enabled"] is False
    assert impersonation.json()["session_token"] is None
    assert blocked_mutation.status_code == 404


def test_academy_admin_cannot_access_platform_governance_routes(
    store: FakeGovernanceStore,
) -> None:
    with TestClient(_app(_academy_admin_claims(), store)) as client:
        create_response = client.post(
            "/api/v2/platform/governance/tenant-exports",
            json={"academy_id": "acad_001", "reason": "should not be allowed"},
        )
        list_response = client.get("/api/v2/platform/governance/tenant-exports")
        status_response = client.get(
            "/api/v2/platform/governance/requests/tenant_export_001/status"
        )

    assert create_response.status_code == 404
    assert list_response.status_code == 404
    assert status_response.status_code == 404
