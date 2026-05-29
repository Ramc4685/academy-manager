from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.shared.http.rate_limit import InMemoryRateLimitMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        limit=2,
        window_seconds=60,
    )
    app.include_router(registration_router, prefix="/api/v2")

    @app.post("/api/v2/parent/onboarding/start")
    async def _start_onboarding() -> dict[str, str]:
        return {"status": "ok"}

    @app.patch("/api/v2/parent/onboarding/{application_id}")
    async def _patch_onboarding(application_id: str) -> dict[str, str]:
        return {"application_id": application_id}

    return app


def test_public_parent_registration_is_rate_limited_with_stable_json() -> None:
    app = _app()

    with TestClient(app, raise_server_exceptions=False) as client:
        responses = [
            client.post(
                "/api/v2/register/parent",
                headers={"Authorization": "Bearer invalid-token"},
            )
            for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [500, 500, 429]
    assert responses[-1].json() == {
        "error": {
            "code": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
            "details": {"retry_after_seconds": 60},
        }
    }


def test_rate_limit_does_not_apply_to_admin_public_shape_paths() -> None:
    app = _app()

    with TestClient(app) as client:
        responses = [client.post("/api/v2/admin/sessions") for _ in range(3)]

    assert [response.status_code for response in responses] == [404, 404, 404]


def test_parent_onboarding_public_write_paths_are_rate_limited() -> None:
    app = _app()

    with TestClient(app) as client:
        start_responses = [client.post("/api/v2/parent/onboarding/start") for _ in range(3)]
        patch_responses = [client.patch("/api/v2/parent/onboarding/app-1") for _ in range(3)]

    assert [response.status_code for response in start_responses] == [200, 200, 429]
    assert [response.status_code for response in patch_responses] == [200, 200, 429]


def test_rate_limit_ignores_spoofed_x_forwarded_for_header() -> None:
    app = _app()

    with TestClient(app, raise_server_exceptions=False) as client:
        responses = [
            client.post(
                "/api/v2/register/parent",
                headers={
                    "Authorization": "Bearer invalid-token",
                    "X-Forwarded-For": f"198.51.100.{index}",
                },
            )
            for index in range(3)
        ]

    assert [response.status_code for response in responses] == [500, 500, 429]
