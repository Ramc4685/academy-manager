"""Interface tests for platform audit routes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.audit.application.use_cases import (
    PlatformAuditService,
    RecordPlatformAuditEventCommand,
)
from backend.v2.interfaces.platform.audit_routes import router as platform_audit_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_platform_audit import (
    FakePlatformAuditRepository,
    _clock,
)


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
        academy_id="acad_blno",
        membership_id="membership_admin",
        roles=("admin",),
    )


def _app(claims: AuthClaims, repo: FakePlatformAuditRepository) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(platform_audit_router, prefix="/api/v2")
    app.state.platform_audit = PlatformAuditService(
        audit_events=repo,
        id_factory=lambda: "audit_001",
        clock=_clock,
    )

    async def _override_claims() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override_claims
    return app


@pytest.fixture()
def repo() -> FakePlatformAuditRepository:
    return FakePlatformAuditRepository()


@pytest.fixture()
def platform_client(repo: FakePlatformAuditRepository) -> Iterator[TestClient]:
    with TestClient(_app(_platform_admin_claims(), repo)) as client:
        yield client


async def _seed(repo: FakePlatformAuditRepository) -> None:
    service = PlatformAuditService(
        audit_events=repo,
        id_factory=lambda: "audit_seed",
        clock=_clock,
    )
    await service.record_event(
        RecordPlatformAuditEventCommand(
            actor_user_id="platform-admin",
            actor_membership_id=None,
            academy_id="acad_blno",
            platform_actor_role="platform_admin",
            action="platform.billing.subscription.activated",
            entity_type="tenant_subscription",
            entity_id="sub_blno",
            before_snapshot={"billing_status": "trialing"},
            after_snapshot={"billing_status": "active"},
            request_id="req_blno",
            ip_address="203.0.113.10",
        )
    )
    await service.record_event(
        RecordPlatformAuditEventCommand(
            actor_user_id="platform-support",
            actor_membership_id=None,
            academy_id="acad_other",
            platform_actor_role="platform_support",
            action="platform.support_impersonation.requested",
            entity_type="support_impersonation_request",
            entity_id="imp_other",
            before_snapshot=None,
            after_snapshot={"status": "requires_manual_approval"},
            request_id="req_other",
            ip_address="203.0.113.11",
        )
    )


@pytest.mark.asyncio
async def test_platform_admin_can_list_platform_audit_events(
    platform_client: TestClient,
    repo: FakePlatformAuditRepository,
) -> None:
    await _seed(repo)

    response = platform_client.get("/api/v2/platform/audit-events")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["events"][0]["action"] == "platform.billing.subscription.activated"
    assert body["events"][0]["academy_id"] == "acad_blno"
    assert body["events"][0]["platform_actor_role"] == "platform_admin"
    assert body["events"][0]["request_id"] == "req_blno"
    assert body["events"][0]["created_at"] == "2026-05-22T16:00:00Z"


@pytest.mark.asyncio
async def test_platform_support_can_list_tenant_scoped_audit_without_cross_tenant_leak(
    repo: FakePlatformAuditRepository,
) -> None:
    await _seed(repo)

    with TestClient(_app(_platform_support_claims(), repo)) as client:
        response = client.get("/api/v2/platform/audit-events?academy_id=acad_other")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [event["academy_id"] for event in body["events"]] == ["acad_other"]
    assert body["events"][0]["entity_id"] == "imp_other"


@pytest.mark.asyncio
async def test_academy_admin_cannot_list_platform_audit_events(
    repo: FakePlatformAuditRepository,
) -> None:
    await _seed(repo)

    with TestClient(_app(_academy_admin_claims(), repo)) as client:
        response = client.get("/api/v2/platform/audit-events?academy_id=acad_blno")

    assert response.status_code == 404
