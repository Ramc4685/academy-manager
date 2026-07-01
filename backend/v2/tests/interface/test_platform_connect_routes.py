"""Interface tests for the platform Stripe Connect onboarding route (Slice I)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.platform.connect_routes import (
    ConnectOnboardingUseCase,
)
from backend.v2.interfaces.platform.connect_routes import (
    router as connect_router,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _FakeConnectOnboarding:
    """Stand-in for the composed use case; records the academy it was called with."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self, *, academy_id: str, refresh_url: str, return_url: str) -> dict:
        self.calls.append(academy_id)
        return {
            "academy_id": academy_id,
            "stripe_account_id": f"acct_{academy_id}",
            "onboarding_url": f"https://connect.stripe.test/onboard/{academy_id}",
            "status": "pending",
        }


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
        academy_id="acad-1",
        membership_id="m-1",
        roles=("admin",),
    )


def _app(claims: AuthClaims, use_case: ConnectOnboardingUseCase) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(connect_router, prefix="/api/v2")
    app.state.platform_connect_onboarding = use_case

    async def _override() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override
    return app


@pytest.fixture()
def use_case() -> _FakeConnectOnboarding:
    return _FakeConnectOnboarding()


@pytest.fixture()
def platform_client(use_case: _FakeConnectOnboarding) -> Iterator[TestClient]:
    with TestClient(_app(_platform_claims(), use_case)) as client:
        yield client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "refresh_url": "https://app.test/connect/refresh",
        "return_url": "https://app.test/connect/return",
    }
    payload.update(overrides)
    return payload


def test_start_onboarding_happy_path(
    platform_client: TestClient, use_case: _FakeConnectOnboarding
) -> None:
    response = platform_client.post(
        "/api/v2/platform/academies/acad-1/connect/onboarding", json=_payload()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["academy_id"] == "acad-1"
    assert body["stripe_account_id"] == "acct_acad-1"
    assert body["onboarding_url"].endswith("/acad-1")
    assert body["status"] == "pending"
    # Tenant resolved explicitly from the path, never a default.
    assert use_case.calls == ["acad-1"]


def test_start_onboarding_resolves_tenant_from_path_not_claims(
    platform_client: TestClient, use_case: _FakeConnectOnboarding
) -> None:
    # The platform admin's own academy_id is "platform-control", but the target
    # academy must come from the path param.
    platform_client.post("/api/v2/platform/academies/acad-99/connect/onboarding", json=_payload())
    assert use_case.calls == ["acad-99"]


def test_start_onboarding_rejects_non_platform_admin(
    use_case: _FakeConnectOnboarding,
) -> None:
    with TestClient(_app(_academy_admin_claims(), use_case)) as client:
        response = client.post(
            "/api/v2/platform/academies/acad-1/connect/onboarding", json=_payload()
        )

    assert response.status_code == 404
    assert use_case.calls == []
