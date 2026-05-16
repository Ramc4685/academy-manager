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


@asynccontextmanager
async def _noop_lifespan(_: FastAPI):
    yield


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
