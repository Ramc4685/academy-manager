from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims


def test_me_returns_mongo_backed_auth_claims() -> None:
    app = FastAPI()
    app.include_router(me_router, prefix="/api/v2")

    async def _claims() -> AuthClaims:
        return AuthClaims(
            user_id="u-admin",
            email="admin@example.com",
            academy_id="academy-a",
            roles=("admin",),
        )

    app.dependency_overrides[get_auth_claims] = _claims

    with TestClient(app) as client:
        response = client.get("/api/v2/me")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "u-admin",
        "email": "admin@example.com",
        "academy_id": "academy-a",
        "roles": ["admin"],
        "membership_id": None,
        "platform_roles": [],
    }


def test_me_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(me_router, prefix="/api/v2")

    with TestClient(app) as client:
        response = client.get("/api/v2/me")

    assert response.status_code == 401
