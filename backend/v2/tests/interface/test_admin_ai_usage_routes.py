"""``GET /api/v2/admin/ai/usage``: the admin persona reads the meter; any
other persona is 404 (Phase 2 slice A3)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.get_ai_usage import AiUsage
from backend.v2.interfaces.admin.ai_usage_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

URL = "/api/v2/admin/ai/usage"
USAGE = AiUsage(used=20, cap=20, tier="free", upgrade_suggested=True, month="2026-11")


class _Wiring:
    class get_ai_usage:
        @staticmethod
        async def execute() -> AiUsage:
            return USAGE


def _client(roles: tuple[str, ...], wiring: object | None = _Wiring()) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    if wiring is not None:
        app.state.ai_usage = wiring
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u", email="u@example.com", academy_id="acad", roles=roles
    )
    return TestClient(app)


def test_admin_reads_the_meter() -> None:
    response = _client(("admin",)).get(URL)
    assert response.status_code == 200
    assert response.json() == {
        "used": 20,
        "cap": 20,
        "tier": "free",
        "upgrade_suggested": True,
        "month": "2026-11",
    }


def test_wrong_persona_is_404() -> None:
    assert _client(("coach",)).get(URL).status_code == 404
    assert _client(("parent",)).get(URL).status_code == 404


def test_unwired_is_503() -> None:
    assert _client(("admin",), wiring=None).get(URL).status_code == 503
