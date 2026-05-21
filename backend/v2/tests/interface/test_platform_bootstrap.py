"""Interface tests for platform tenant bootstrap."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
)
from backend.v2.interfaces.platform.bootstrap_routes import router as platform_bootstrap_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

from backend.v2.tests.application.test_bootstrap_academy import FakeBootstrapStore


def _platform_claims() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _academy_admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="academy-admin",
        email="admin@example.com",
        academy_id="academy-a",
        membership_id="membership-a",
        roles=("admin",),
    )


def _app(claims: AuthClaims, store: FakeBootstrapStore) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(platform_bootstrap_router, prefix="/api/v2")
    app.state.bootstrap_academy = BootstrapAcademy(
        store=store,
        id_factory=lambda prefix: f"{prefix}test",
    )

    async def _override_claims() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override_claims
    return app


@pytest.fixture()
def store() -> FakeBootstrapStore:
    return FakeBootstrapStore()


@pytest.fixture()
def platform_client(store: FakeBootstrapStore) -> Iterator[TestClient]:
    with TestClient(_app(_platform_claims(), store)) as client:
        yield client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": "North Shore Badminton",
        "slug": "north-shore",
        "primary_domain": "north.example.com",
        "owner_email": "owner@example.com",
        "owner_display_name": "Owner One",
        "timezone": "America/Chicago",
    }
    payload.update(overrides)
    return payload


def test_platform_bootstrap_route_creates_membership_and_settings_records(
    platform_client: TestClient,
    store: FakeBootstrapStore,
) -> None:
    response = platform_client.post("/api/v2/platform/academies/bootstrap", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["academy_id"] == "acad_test"
    assert body["owner_role"] == "admin"
    assert body["default_records"] == [
        "academy",
        "owner_user",
        "owner_membership",
        "academy_settings",
        "billing_policy",
        "waiver_template",
        "roles",
        "feature_flags",
    ]

    owner = store.users["owner@example.com"]
    assert store.memberships[(body["academy_id"], owner["user_id"])]["roles"] == ["admin"]
    assert body["academy_id"] in store.settings
    assert body["academy_id"] in store.billing_policies
    assert body["academy_id"] in store.waivers
    assert body["academy_id"] in store.feature_flags


def test_platform_bootstrap_route_is_idempotent(platform_client: TestClient) -> None:
    first = platform_client.post("/api/v2/platform/academies/bootstrap", json=_payload())
    second = platform_client.post("/api/v2/platform/academies/bootstrap", json=_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["academy_id"] == second.json()["academy_id"]
    assert second.json()["created"] is False


def test_platform_bootstrap_rejects_non_platform_admin(store: FakeBootstrapStore) -> None:
    with TestClient(_app(_academy_admin_claims(), store)) as client:
        response = client.post("/api/v2/platform/academies/bootstrap", json=_payload())

    assert response.status_code == 404


def test_platform_bootstrap_returns_conflict_for_duplicate_slug(
    platform_client: TestClient,
) -> None:
    first = platform_client.post("/api/v2/platform/academies/bootstrap", json=_payload())
    conflict = platform_client.post(
        "/api/v2/platform/academies/bootstrap",
        json=_payload(primary_domain="other.example.com", owner_email="other@example.com"),
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "Identity.BootstrapSlugConflict"


def test_route_uses_command_shape_without_legacy_defaults() -> None:
    command = BootstrapAcademyCommand(**_payload())
    assert command.slug == "north-shore"
    assert command.primary_domain == "north.example.com"
