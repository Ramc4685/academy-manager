"""POST /api/v2/password-reset answers 204 whatever the address."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.password_reset_routes import (
    PasswordResetRequest,
    request_password_reset,
    router,
)


def _client(use_case) -> TestClient:
    app = FastAPI()
    app.state.send_password_reset_email = use_case
    app.state.default_academy_id = "acad-1"
    app.include_router(router, prefix="/api/v2")
    return TestClient(app)


def test_always_204_and_falls_back_to_the_default_academy() -> None:
    use_case = AsyncMock()
    response = _client(use_case).post(
        "/api/v2/password-reset", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 204
    use_case.execute.assert_awaited_once_with("nobody@example.com", academy_id="acad-1")


def test_the_host_resolved_academy_wins_over_the_default() -> None:
    use_case = AsyncMock()
    app = FastAPI()
    app.state.send_password_reset_email = use_case
    app.state.default_academy_id = "acad-default"

    @app.middleware("http")
    async def _tenant(request, call_next):  # type: ignore[no-untyped-def]
        request.state.resolved_academy_id = "acad-host"
        return await call_next(request)

    app.include_router(router, prefix="/api/v2")
    response = TestClient(app).post("/api/v2/password-reset", json={"email": "a@example.com"})

    assert response.status_code == 204
    use_case.execute.assert_awaited_once_with("a@example.com", academy_id="acad-host")


def test_the_send_runs_after_the_response_not_inline() -> None:
    # Regression: awaiting the send inline made response time a membership oracle.
    use_case = AsyncMock()
    request = SimpleNamespace(
        state=SimpleNamespace(resolved_academy_id="acad-1"),
        app=SimpleNamespace(
            state=SimpleNamespace(saas_mode=True, send_password_reset_email=use_case)
        ),
    )
    tasks = BackgroundTasks()

    asyncio.run(
        request_password_reset(
            request,  # type: ignore[arg-type]
            PasswordResetRequest(email="a@example.com"),
            tasks,
        )
    )

    use_case.execute.assert_not_awaited()
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func is use_case.execute


def test_saas_mode_without_a_tenant_is_400() -> None:
    use_case = AsyncMock()
    client = _client(use_case)
    client.app.state.saas_mode = True

    response = client.post("/api/v2/password-reset", json={"email": "a@example.com"})

    assert response.status_code == 400
    use_case.execute.assert_not_awaited()
