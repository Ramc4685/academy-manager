"""The anonymous public academy page read is rate limited per client (Lane B2)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.http.rate_limit import InMemoryRateLimitMiddleware

URL = "/api/v2/public/academy"


def _app(clock: list[float]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(InMemoryRateLimitMiddleware, clock=lambda: clock[0])

    @app.get(URL)
    async def _page() -> dict[str, str]:
        return {"state": "published"}

    @app.post(URL)
    async def _post() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_public_page_get_is_limited_per_client_ip_with_retry_after() -> None:
    clock = [1000.0]
    client = TestClient(_app(clock))
    headers = {"fly-client-ip": "203.0.113.7"}
    for _ in range(120):
        assert client.get(URL, headers=headers).status_code == 200
    blocked = client.get(URL, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(blocked.headers["Retry-After"]) >= 1

    # Another visitor is unaffected; the window resets after 60 seconds.
    assert client.get(URL, headers={"fly-client-ip": "203.0.113.8"}).status_code == 200
    clock[0] += 61
    assert client.get(URL, headers=headers).status_code == 200


def test_limit_is_keyed_to_the_get_read_only() -> None:
    clock = [1000.0]
    client = TestClient(_app(clock))
    headers = {"fly-client-ip": "203.0.113.9"}
    for _ in range(130):
        assert client.post(URL, headers=headers).status_code == 200
