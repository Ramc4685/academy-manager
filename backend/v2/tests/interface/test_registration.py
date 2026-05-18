from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.domain.models import User
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.shared.http import register_exception_handlers


class FakeRegisterPublicParent:
    async def execute(self, id_token: str) -> User:
        assert id_token == "firebase-token"
        return User(
            user_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            roles=("parent",),
            is_active=True,
            academy_id="academy-a",
        )


def test_public_parent_registration_requires_bearer_token() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.register_public_parent = FakeRegisterPublicParent()
    app.include_router(registration_router, prefix="/api/v2")

    with TestClient(app) as client:
        response = client.post("/api/v2/register/parent")

    assert response.status_code == 401


def test_public_parent_registration_returns_parent_auth_row() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.register_public_parent = FakeRegisterPublicParent()
    app.include_router(registration_router, prefix="/api/v2")

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/register/parent",
            headers={"Authorization": "Bearer firebase-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "parent-1",
        "email": "parent@example.com",
        "academy_id": "academy-a",
        "roles": ["parent"],
    }
