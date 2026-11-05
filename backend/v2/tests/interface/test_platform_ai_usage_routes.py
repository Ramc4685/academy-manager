"""``GET /api/v2/platform/academies/{academy_id}/ai-usage``: platform admin
only; unknown academy and any other persona are 404 (Phase 2 slice A3)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.get_ai_usage import AiUsage
from backend.v2.contexts.ai.domain.errors import AiAcademyNotFound
from backend.v2.interfaces.platform.ai_usage_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

URL = "/api/v2/platform/academies/acad-1/ai-usage"
USAGE = AiUsage(used=3, cap=200, tier="growth", upgrade_suggested=False, month="2026-11")


class _ForAcademy:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def execute(self, academy_id: str) -> AiUsage:
        self.asked.append(academy_id)
        if academy_id != "acad-1":
            raise AiAcademyNotFound("academy not found", academy_id=academy_id)
        return USAGE


class _Wiring:
    def __init__(self) -> None:
        self.get_ai_usage_for_academy = _ForAcademy()


def _platform_admin() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _platform_support() -> AuthClaims:
    return AuthClaims(
        user_id="platform-support",
        email="support@example.com",
        academy_id="platform-control",
        platform_roles=("platform_support",),
    )


def _academy_admin() -> AuthClaims:
    return AuthClaims(
        user_id="academy-admin",
        email="admin@example.com",
        academy_id="acad-1",
        membership_id="m-1",
        roles=("admin", "owner"),
    )


def _client(claims: AuthClaims, wiring: _Wiring) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2")
    app.state.ai_usage = wiring

    async def _override() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override
    return TestClient(app)


def test_platform_admin_reads_the_academy_meter() -> None:
    wiring = _Wiring()
    response = _client(_platform_admin(), wiring).get(URL)
    assert response.status_code == 200
    assert response.json() == USAGE.model_dump()
    assert wiring.get_ai_usage_for_academy.asked == ["acad-1"]


def test_unknown_academy_is_404() -> None:
    response = _client(_platform_admin(), _Wiring()).get(
        "/api/v2/platform/academies/acad-missing/ai-usage"
    )
    assert response.status_code == 404


@pytest.mark.parametrize("claims", [_academy_admin(), _platform_support()])
def test_non_platform_admins_are_404(claims: AuthClaims) -> None:
    wiring = _Wiring()
    assert _client(claims, wiring).get(URL).status_code == 404
    assert wiring.get_ai_usage_for_academy.asked == []
