"""``POST/DELETE /api/v2/me/devices`` (mobile M2).

Mounts the ``me`` router over the real Mongo repository on mongomock with
migration 0215's indexes, so uniqueness on ``token`` is enforced like
production. A stand-in middleware sets the tenant ContextVar from the caller's
claims, as ``TenancyMiddleware`` does.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.use_cases.register_push_device import (
    RegisterPushDevice,
)
from backend.v2.contexts.communications.application.use_cases.unregister_push_device import (
    UnregisterPushDevice,
)
from backend.v2.contexts.communications.infrastructure.mongo_push_device_repo import (
    MongoPushDeviceRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_push_token_audit import (
    MongoPushTokenAudit,
)
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy.context import _current as _tenant_var

BODY = {"token": "fcm-1", "platform": "ios", "app_version": "1.0.0"}


@pytest.fixture
async def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    database = mongomock_motor.AsyncMongoMockClient()["me-devices"]
    await importlib.import_module("backend.v2.migrations.0215_push_devices").up(database)
    return database


def _app(db: Any, *, user_id: str | None, academy_id: str = "acad-a") -> FastAPI:
    app = FastAPI()
    app.include_router(me_router, prefix="/api/v2")
    repo = MongoPushDeviceRepository(db)
    app.state.register_push_device = RegisterPushDevice(devices=repo, audit=MongoPushTokenAudit(db))
    app.state.unregister_push_device = UnregisterPushDevice(devices=repo)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        token = _tenant_var.set(academy_id)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    if user_id is not None:

        async def _claims() -> AuthClaims:
            return AuthClaims(
                user_id=user_id, email=f"{user_id}@example.com", academy_id=academy_id, roles=()
            )

        app.dependency_overrides[get_auth_claims] = _claims
    return app


@pytest.mark.asyncio
async def test_unauthenticated_calls_are_401(db: Any) -> None:
    with TestClient(_app(db, user_id=None)) as client:
        assert client.post("/api/v2/me/devices", json=BODY).status_code == 401
        assert client.delete("/api/v2/me/devices/fcm-1").status_code == 401
    assert await db["push_devices"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_register_is_idempotent_and_owned_by_the_caller(db: Any) -> None:
    with TestClient(_app(db, user_id="u1")) as client:
        first = client.post("/api/v2/me/devices", json={**BODY, "user_id": "someone-else"})
        second = client.post("/api/v2/me/devices", json=BODY)

    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["platform"] == "ios"
    rows = await db["push_devices"].find({}).to_list(None)
    assert [(r["user_id"], r["academy_id"]) for r in rows] == [("u1", "acad-a")]
    assert await db["audit_logs"].count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "platform": "web"},
        {**BODY, "token": ""},
        {"platform": "ios"},
    ],
)
async def test_malformed_registration_is_422(db: Any, body: dict[str, Any]) -> None:
    with TestClient(_app(db, user_id="u1")) as client:
        assert client.post("/api/v2/me/devices", json=body).status_code == 422


@pytest.mark.asyncio
async def test_shared_phone_moves_the_token_to_the_new_user(db: Any) -> None:
    with TestClient(_app(db, user_id="mom")) as client:
        client.post("/api/v2/me/devices", json=BODY)
    with TestClient(_app(db, user_id="dad", academy_id="acad-b")) as client:
        client.post("/api/v2/me/devices", json=BODY)

    rows = await db["push_devices"].find({}).to_list(None)
    assert [(r["user_id"], r["academy_id"]) for r in rows] == [("dad", "acad-b")]
    audits = await db["audit_logs"].find({"action": "push_device.token_moved"}).to_list(None)
    assert [(a["academy_id"], a["before"], a["after"]) for a in audits] == [
        (
            "acad-b",
            {"user_id": "mom", "academy_id": "acad-a"},
            {"user_id": "dad", "academy_id": "acad-b"},
        )
    ]
    assert "fcm-1" not in str(audits)


@pytest.mark.asyncio
async def test_only_the_holder_can_delete_and_missing_is_a_no_op(db: Any) -> None:
    with TestClient(_app(db, user_id="u1")) as client:
        client.post("/api/v2/me/devices", json=BODY)
    with TestClient(_app(db, user_id="u2")) as client:
        assert client.delete("/api/v2/me/devices/fcm-1").status_code == 204
    with TestClient(_app(db, user_id="u1", academy_id="acad-b")) as client:
        assert client.delete("/api/v2/me/devices/fcm-1").status_code == 204
    assert await db["push_devices"].count_documents({}) == 1

    with TestClient(_app(db, user_id="u1")) as client:
        assert client.delete("/api/v2/me/devices/fcm-1").status_code == 204
        assert client.delete("/api/v2/me/devices/never-registered").status_code == 204
    assert await db["push_devices"].count_documents({}) == 0
