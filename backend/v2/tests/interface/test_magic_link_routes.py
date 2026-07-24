from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.application.use_cases.magic_link import ConsumedMagicLink
from backend.v2.contexts.identity.domain.errors import MagicLinkExpired, MagicLinkInvalid
from backend.v2.interfaces.magic_link_routes import router as magic_link_router
from backend.v2.shared.http import register_exception_handlers


class _FakeConsume:
    def __init__(self, *, result: ConsumedMagicLink | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.received: tuple[str, str] | None = None

    async def execute(self, token: str, *, academy_id: str) -> ConsumedMagicLink:
        self.received = (token, academy_id)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _app(fake: _FakeConsume, *, saas_mode: bool = False) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.consume_magic_link = fake
    app.state.saas_mode = saas_mode
    app.include_router(magic_link_router, prefix="/api/v2")
    return app


def _with_resolved_tenant(app: FastAPI, academy_id: str) -> None:
    @app.middleware("http")
    async def _inject(request, call_next):  # type: ignore[no-untyped-def]
        request.state.resolved_academy_id = academy_id
        return await call_next(request)


def test_consume_success_returns_custom_token_and_next_path() -> None:
    fake = _FakeConsume(
        result=ConsumedMagicLink(custom_token="ct-123", next_path="/parent/payments")
    )
    app = _app(fake)
    _with_resolved_tenant(app, "acad-a")

    with TestClient(app) as client:
        response = client.post("/api/v2/magic-link/consume", json={"token": "raw-tok"})

    assert response.status_code == 200
    assert response.json() == {"custom_token": "ct-123", "next_path": "/parent/payments"}
    assert fake.received == ("raw-tok", "acad-a")


def test_consume_invalid_token_maps_to_401() -> None:
    fake = _FakeConsume(error=MagicLinkInvalid())
    app = _app(fake)
    _with_resolved_tenant(app, "acad-a")

    with TestClient(app) as client:
        response = client.post("/api/v2/magic-link/consume", json={"token": "bad"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "Identity.MagicLinkInvalid"


def test_consume_expired_token_maps_to_410() -> None:
    fake = _FakeConsume(error=MagicLinkExpired())
    app = _app(fake)
    _with_resolved_tenant(app, "acad-a")

    with TestClient(app) as client:
        response = client.post("/api/v2/magic-link/consume", json={"token": "old"})

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "Identity.MagicLinkExpired"


def test_consume_is_post_only() -> None:
    fake = _FakeConsume(result=ConsumedMagicLink(custom_token="x", next_path="/parent/dashboard"))
    app = _app(fake)

    with TestClient(app) as client:
        # A mail-scanner prefetch GET must not be able to reach (and burn) a token.
        response = client.get("/api/v2/magic-link/consume")

    assert response.status_code == 405


def test_consume_saas_mode_400_when_tenant_unresolved() -> None:
    fake = _FakeConsume(result=ConsumedMagicLink(custom_token="x", next_path="/parent/dashboard"))
    app = _app(fake, saas_mode=True)  # no resolved tenant injected

    with TestClient(app) as client:
        response = client.post("/api/v2/magic-link/consume", json={"token": "raw-tok"})

    assert response.status_code == 400
    assert fake.received is None  # use case never invoked


def test_consume_requires_token_field() -> None:
    fake = _FakeConsume(result=ConsumedMagicLink(custom_token="x", next_path="/parent/dashboard"))
    app = _app(fake)
    _with_resolved_tenant(app, "acad-a")

    with TestClient(app) as client:
        response = client.post("/api/v2/magic-link/consume", json={})

    assert response.status_code == 422  # pydantic validation
    assert fake.received is None
