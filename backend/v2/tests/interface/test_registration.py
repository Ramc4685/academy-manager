from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.domain.models import User
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.shared.http import register_exception_handlers


class FakeRegisterPublicParent:
    def __init__(self) -> None:
        self.received_academy_id: str | None = None

    async def execute(self, id_token: str, *, academy_id: str | None = None) -> User:
        assert id_token == "firebase-token"
        self.received_academy_id = academy_id
        return User(
            user_id="parent-1",
            email="parent@example.com",
            display_name="Parent One",
            roles=("parent",),
            is_active=True,
            # Echo the resolved tenant so the route response reflects what
            # the use case received (mirrors real behavior).
            academy_id=academy_id or "academy-a",
        )


def _app(saas_mode: bool = False) -> tuple[FastAPI, FakeRegisterPublicParent]:
    app = FastAPI()
    register_exception_handlers(app)
    fake = FakeRegisterPublicParent()
    app.state.register_public_parent = fake
    app.state.saas_mode = saas_mode
    app.include_router(registration_router, prefix="/api/v2")
    return app, fake


def test_public_parent_registration_requires_bearer_token() -> None:
    app, _ = _app()
    with TestClient(app) as client:
        response = client.post("/api/v2/register/parent")
    assert response.status_code == 401


def test_public_parent_registration_returns_parent_auth_row_legacy() -> None:
    """Non-SaaS mode: no resolved_academy_id on request.state is fine;
    the use case falls back to default_academy_id internally."""
    app, fake = _app(saas_mode=False)
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
    # Route passes None when no tenant was resolved; the use case decides
    # whether that is acceptable based on saas_mode.
    assert fake.received_academy_id is None


def test_public_parent_registration_saas_mode_400_when_tenant_unresolved() -> None:
    """SaaS mode + no tenant resolved by middleware ⇒ route returns 400.
    Prevents the #81 regression where parents silently landed in
    ``default-academy``."""
    app, fake = _app(saas_mode=True)
    with TestClient(app) as client:
        response = client.post(
            "/api/v2/register/parent",
            headers={"Authorization": "Bearer firebase-token"},
        )
    assert response.status_code == 400
    assert fake.received_academy_id is None


def test_public_parent_registration_saas_mode_passes_resolved_tenant() -> None:
    """SaaS mode + resolved tenant from middleware ⇒ route forwards
    academy_id to the use case and the response reflects it."""
    app, fake = _app(saas_mode=True)

    # Simulate the TenancyMiddleware having stamped request.state with
    # the resolved tenant. ``app.middleware`` hook lets us set it for
    # this test without re-implementing the whole middleware.
    @app.middleware("http")
    async def _inject_resolved_tenant(request, call_next):
        request.state.resolved_academy_id = "acad_acme"
        return await call_next(request)

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/register/parent",
            headers={"Authorization": "Bearer firebase-token"},
        )
    assert response.status_code == 200
    assert response.json()["academy_id"] == "acad_acme"
    assert fake.received_academy_id == "acad_acme"
