"""Tests proving legacy routes return 410 in SaaS mode and v2 routes pass through."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.http.saas_guard import SaasLegacyRouteGuard


def _make_app(*, saas_mode: bool) -> FastAPI:
    app = FastAPI()
    if saas_mode:
        app.add_middleware(SaasLegacyRouteGuard)

    @app.get("/api/sessions")
    async def legacy_sessions():
        return {"ok": True}

    @app.get("/api/v2/healthz")
    async def v2_health():
        return {"status": "ok"}

    @app.get("/api/auth/login")
    async def legacy_auth():
        return {"ok": True}

    return app


def test_legacy_route_blocked_in_saas_mode() -> None:
    client = TestClient(_make_app(saas_mode=True))
    r = client.get("/api/sessions")
    assert r.status_code == 410
    assert "Legacy" in r.json()["detail"]


def test_v2_route_allowed_in_saas_mode() -> None:
    client = TestClient(_make_app(saas_mode=True))
    r = client.get("/api/v2/healthz")
    assert r.status_code == 200


def test_legacy_route_allowed_when_saas_mode_off() -> None:
    client = TestClient(_make_app(saas_mode=False))
    r = client.get("/api/sessions")
    assert r.status_code == 200


def test_another_legacy_path_blocked_in_saas_mode() -> None:
    client = TestClient(_make_app(saas_mode=True))
    r = client.get("/api/auth/login")
    assert r.status_code == 410


def test_response_is_json_in_saas_mode() -> None:
    client = TestClient(_make_app(saas_mode=True))
    r = client.get("/api/sessions")
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert "detail" in body
