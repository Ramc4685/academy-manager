"""Smoke test for /api/v2/healthz.

We don't connect to Mongo in this test — the lifespan opens a client lazily.
We patch the lifespan with an empty one so create_app() can be exercised in
isolation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.config import get_settings
from backend.v2.tests._route_paths import route_paths


@asynccontextmanager
async def _noop_lifespan(_: FastAPI):
    yield


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from backend.v2 import main as v2_main

    monkeypatch.setattr(v2_main, "_lifespan", _noop_lifespan)
    return v2_main.create_app()


def test_healthz_returns_ok(app: FastAPI) -> None:
    with TestClient(app) as client:
        r = client.get("/api/v2/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_openapi_title_is_public_product_name(app: FastAPI) -> None:
    assert app.title == "Academy Manager API"
    assert app.version == "2.0.0"


def test_platform_routes_are_mounted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.v2 import main as v2_main

    monkeypatch.setattr(v2_main, "_lifespan", _noop_lifespan)
    app = v2_main.create_app()

    paths = route_paths(app)
    assert any(path.startswith("/api/v2/platform") for path in paths)


def test_platform_routes_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.v2 import main as v2_main

    monkeypatch.setenv("ENABLE_PLATFORM_ROUTES", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(v2_main, "_lifespan", _noop_lifespan)
    app = v2_main.create_app()

    paths = route_paths(app)
    assert not any(path.startswith("/api/v2/platform") for path in paths)
