"""POST /api/v2/password-reset answers 204 whatever the address."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.password_reset_routes import router


def _client(use_case) -> TestClient:
    app = FastAPI()
    app.state.send_password_reset_email = use_case
    app.state.default_academy_id = "acad-1"
    app.include_router(router, prefix="/api/v2")
    return TestClient(app)


def test_always_204_and_passes_the_resolved_academy() -> None:
    use_case = AsyncMock()
    response = _client(use_case).post(
        "/api/v2/password-reset", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 204
    use_case.execute.assert_awaited_once_with("nobody@example.com", academy_id="acad-1")


def test_saas_mode_without_a_tenant_is_400() -> None:
    use_case = AsyncMock()
    client = _client(use_case)
    client.app.state.saas_mode = True

    response = client.post("/api/v2/password-reset", json={"email": "a@example.com"})

    assert response.status_code == 400
    use_case.execute.assert_not_awaited()
