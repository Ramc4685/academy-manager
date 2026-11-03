"""``GET /api/v2/admin/account-deletions`` (mobile M5, D4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.application.use_cases.list_account_deletions import (
    ListAccountDeletions,
)
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)
from backend.v2.interfaces.admin.account_deletion_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant_var

URL = "/api/v2/admin/account-deletions"
T0 = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.fixture
async def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    database = mongomock_motor.AsyncMongoMockClient()["admin-account-deletions"]
    await database["users"].insert_one({"user_id": "u1", "display_name": "Pat Parent"})
    base = {
        "auth_uid": "fb",
        "email": "x@example.com",
        "requested_at": T0,
        "execute_after": T0 + timedelta(days=14),
        "status": "scheduled",
    }
    await database["account_deletion_requests"].insert_many(
        [
            {
                **base,
                "request_id": "r1",
                "user_id": "u1",
                "aliases": ["u1", "fb1"],
                "academy_ids": ["acad-a", "acad-b"],
                "attempts": 2,
                "last_error": {"step": "billing", "error": "boom", "at": T0},
            },
            {
                **base,
                "request_id": "r2",
                "user_id": "u2",
                "aliases": ["u2"],
                "academy_ids": ["acad-b"],
            },
        ]
    )
    return database


def _app(db: Any, roles: tuple[str, ...]) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    app.state.list_account_deletions = ListAccountDeletions(store=MongoAccountDeletionStore(db))

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        token = _tenant_var.set("acad-a")
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    async def _claims() -> AuthClaims:
        return AuthClaims(user_id="admin", email="a@x.com", academy_id="acad-a", roles=roles)

    app.dependency_overrides[get_auth_claims] = _claims
    return app


@pytest.mark.asyncio
async def test_admin_sees_this_academys_requests_without_the_email(db: Any) -> None:
    with TestClient(_app(db, ("admin",))) as client:
        res = client.get(URL)
    assert res.status_code == 200
    rows = res.json()["deletions"]
    assert [r["request_id"] for r in rows] == ["r1"]
    row = rows[0]
    assert row["display_name"] == "Pat Parent"
    assert row["aliases"] == ["u1", "fb1"]
    assert (row["attempts"], row["failing_step"]) == (2, "billing")
    assert "email" not in row and "x@example.com" not in res.text


@pytest.mark.asyncio
async def test_a_parent_cannot_list_deletions(db: Any) -> None:
    with TestClient(_app(db, ("parent",))) as client:
        assert client.get(URL).status_code == 404
