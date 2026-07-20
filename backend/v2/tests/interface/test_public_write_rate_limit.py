from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.shared.http.rate_limit import InMemoryRateLimitMiddleware


def _app(proxy_shared_secret: str | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        limit=2,
        window_seconds=60,
        proxy_shared_secret=proxy_shared_secret,
    )
    app.include_router(registration_router, prefix="/api/v2")

    @app.post("/api/v2/parent/onboarding/start")
    async def _start_onboarding() -> dict[str, str]:
        return {"status": "ok"}

    @app.patch("/api/v2/parent/onboarding/{application_id}")
    async def _patch_onboarding(application_id: str) -> dict[str, str]:
        return {"application_id": application_id}

    # Same path as the real route: parent router (prefix /parent) mounted
    # under /api/v2 in main.py.
    @app.post("/api/v2/parent/webhooks/stripe")
    async def _stripe_webhook() -> dict[str, str]:
        return {"status": "accepted"}

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


def test_trusted_proxy_keys_on_cf_connecting_ip_with_independent_buckets() -> None:
    app = _app(proxy_shared_secret="s3cret")

    with TestClient(app) as client:
        first_ip = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={"x-cm-proxy-auth": "s3cret", "CF-Connecting-IP": "203.0.113.10"},
            )
            for _ in range(3)
        ]
        second_ip = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={"x-cm-proxy-auth": "s3cret", "CF-Connecting-IP": "203.0.113.20"},
            )
            for _ in range(3)
        ]

    # Each end-client IP gets its own bucket — no shared-proxy bucket.
    assert [response.status_code for response in first_ip] == [200, 200, 429]
    assert [response.status_code for response in second_ip] == [200, 200, 429]


def test_forged_cf_connecting_ip_without_secret_does_not_rotate_buckets() -> None:
    app = _app(proxy_shared_secret="s3cret")

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={
                    "x-cm-proxy-auth": "wrong-secret",
                    "CF-Connecting-IP": f"198.51.100.{index}",
                    "Fly-Client-IP": "192.0.2.7",
                },
            )
            for index in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]


def test_cf_connecting_ip_is_untrusted_when_no_secret_configured() -> None:
    app = _app(proxy_shared_secret=None)

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={
                    "x-cm-proxy-auth": "anything",
                    "CF-Connecting-IP": f"198.51.100.{index}",
                    "Fly-Client-IP": "192.0.2.7",
                },
            )
            for index in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]


def test_empty_string_secret_behaves_as_unset() -> None:
    app = _app(proxy_shared_secret="")

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={
                    "x-cm-proxy-auth": "",
                    "CF-Connecting-IP": f"198.51.100.{index}",
                    "Fly-Client-IP": "192.0.2.7",
                },
            )
            for index in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 429]


def test_fly_client_ip_keys_direct_hits_before_request_client() -> None:
    app = _app()

    with TestClient(app) as client:
        first = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={"Fly-Client-IP": "192.0.2.1"},
            )
            for _ in range(3)
        ]
        second = [
            client.post(
                "/api/v2/parent/onboarding/start",
                headers={"Fly-Client-IP": "192.0.2.2"},
            )
            for _ in range(3)
        ]

    assert [response.status_code for response in first] == [200, 200, 429]
    assert [response.status_code for response in second] == [200, 200, 429]


def test_stripe_webhook_has_high_ceiling_and_parent_paths_keep_low_limit() -> None:
    app = _app()

    with TestClient(app) as client:
        webhook_statuses = [
            client.post("/api/v2/parent/webhooks/stripe").status_code for _ in range(601)
        ]
        parent_statuses = [
            client.post("/api/v2/parent/onboarding/start").status_code for _ in range(3)
        ]
        over_limit = client.post("/api/v2/parent/webhooks/stripe")

    assert webhook_statuses[:600] == [200] * 600
    assert webhook_statuses[600] == 429
    assert over_limit.status_code == 429
    assert over_limit.headers.get("Retry-After") is not None
    assert parent_statuses == [200, 200, 429]


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
