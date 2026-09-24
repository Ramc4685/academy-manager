"""L9d interface: export and purge dry-run are platform-admin only."""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.application.use_cases.tenant_data_offboarding import (
    TenantDataOffboardingService,
)
from backend.v2.contexts.platform.audit.application.use_cases import (
    RecordPlatformAuditEventCommand,
)
from backend.v2.contexts.platform.domain.models import Tenant
from backend.v2.interfaces.platform.router import router as platform_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_tenant_lifecycle import FakeTenantRepository

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class FakeTenantDataStore:
    """Mirrors MongoTenantDataStore: every read filters on academy_id."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self._rows = rows

    async def collection_names(self) -> list[str]:
        return list(self._rows)

    async def count(self, collection: str, academy_id: str) -> int:
        return sum(1 for row in self._rows.get(collection, []) if row["academy_id"] == academy_id)

    async def documents(self, collection: str, academy_id: str) -> AsyncIterator[dict[str, Any]]:
        for row in self._rows.get(collection, []):
            if row["academy_id"] == academy_id:
                yield row


def _tenant(academy_id: str, status: str) -> Tenant:
    return Tenant(
        academy_id=academy_id,
        display_name="Synthetic Club",
        slug=academy_id,
        primary_domain=f"{academy_id}.example.test",
        status=status,  # type: ignore[arg-type]
        plan_code="starter",
        created_by="platform-admin",
        updated_by="platform-admin",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _claims(kind: str) -> AuthClaims:
    if kind == "platform_admin":
        return AuthClaims(
            user_id="platform-admin",
            email="ops@example.com",
            academy_id="platform-control",
            platform_roles=("platform_admin",),
        )
    if kind == "platform_support":
        return AuthClaims(
            user_id="platform-support",
            email="support@example.com",
            academy_id="platform-control",
            platform_roles=("platform_support",),
        )
    return AuthClaims(
        user_id="academy-owner",
        email="owner@example.com",
        academy_id="acad_live",
        membership_id="membership-a",
        roles=("admin",),
    )


def _client(kind: str) -> tuple[TestClient, list[RecordPlatformAuditEventCommand]]:
    repo = FakeTenantRepository()
    repo.tenants["acad_live"] = _tenant("acad_live", "active")
    repo.tenants["acad_gone"] = _tenant("acad_gone", "cancelled")
    audits: list[RecordPlatformAuditEventCommand] = []

    async def _record(command: RecordPlatformAuditEventCommand) -> object:
        audits.append(command)
        return None

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(platform_router, prefix="/api/v2")
    app.state.tenant_data_offboarding = TenantDataOffboardingService(
        tenants=repo,
        data=FakeTenantDataStore(
            {
                "students": [
                    {"academy_id": "acad_live", "student_id": "s1"},
                    {"academy_id": "acad_gone", "student_id": "s2"},
                ],
            }
        ),
        audit_recorder=_record,
        clock=lambda: _NOW,
    )

    async def _override() -> AuthClaims:
        return _claims(kind)

    app.dependency_overrides[get_auth_claims] = _override
    return TestClient(app), audits


@pytest.mark.parametrize("kind", ["platform_support", "academy_owner"])
def test_non_platform_admins_get_404(kind: str) -> None:
    client, audits = _client(kind)
    export = client.post("/api/v2/platform/tenants/acad_live/data-export", json={"reason": "x"})
    preview = client.post("/api/v2/platform/tenants/acad_gone/purge-dry-run")
    assert export.status_code == 404
    assert preview.status_code == 404
    assert audits == []


def test_platform_admin_downloads_a_zip_of_only_that_tenant() -> None:
    client, audits = _client("platform_admin")
    response = client.post(
        "/api/v2/platform/tenants/acad_live/data-export", json={"reason": "offboarding"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "tenant-export-acad_live-" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        body = zf.read("collections/students.jsonl").decode()
    assert '"s1"' in body and '"s2"' not in body
    assert [a.action for a in audits] == ["tenant.data_exported"]


def test_export_requires_a_reason() -> None:
    client, _ = _client("platform_admin")
    response = client.post("/api/v2/platform/tenants/acad_live/data-export", json={"reason": " "})
    assert response.status_code == 422


def test_export_of_unknown_tenant_is_404() -> None:
    client, audits = _client("platform_admin")
    response = client.post("/api/v2/platform/tenants/acad_nope/data-export", json={"reason": "x"})
    assert response.status_code == 404
    assert audits == []


def test_purge_dry_run_refuses_an_active_tenant() -> None:
    client, audits = _client("platform_admin")
    response = client.post("/api/v2/platform/tenants/acad_live/purge-dry-run")
    assert response.status_code == 409
    assert audits == []


def test_purge_dry_run_on_a_cancelled_tenant_returns_counts() -> None:
    client, audits = _client("platform_admin")
    response = client.post("/api/v2/platform/tenants/acad_gone/purge-dry-run")
    assert response.status_code == 200
    body = response.json()
    assert body["would_delete"] == [{"collection": "students", "count": 1}]
    assert body["total_to_delete"] == 1
    assert body["executed"] is False
    assert body["confirm_token"].startswith("purge_")
    assert [a.action for a in audits] == ["tenant.purge_dry_run"]
