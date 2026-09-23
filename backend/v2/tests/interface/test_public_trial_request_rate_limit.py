"""The anonymous trial form is rate limited per client IP and per host (Lane B4)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.http.rate_limit import InMemoryRateLimitMiddleware

URL = "/api/v2/public/trial-requests"
HOST = "riverside-academy.courtmastr.test"


def _app(clock: list[float]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(InMemoryRateLimitMiddleware, clock=lambda: clock[0])

    @app.post(URL)
    async def _submit() -> dict[str, str]:
        return {"state": "received"}

    return app


def _post(client: TestClient, ip: str, host: str = HOST) -> int:
    return client.post(URL, json={}, headers={"fly-client-ip": ip, "host": host}).status_code


def test_ten_per_client_ip_per_ten_minutes() -> None:
    clock = [1000.0]
    client = TestClient(_app(clock))
    for _ in range(10):
        assert _post(client, "203.0.113.7") == 200
    blocked = client.post(URL, json={}, headers={"fly-client-ip": "203.0.113.7", "host": HOST})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(blocked.headers["Retry-After"]) > 60

    # Another family is unaffected; the window resets after ten minutes.
    assert _post(client, "203.0.113.8") == 200
    clock[0] += 601
    assert _post(client, "203.0.113.7") == 200


def test_one_host_is_capped_across_many_client_ips() -> None:
    clock = [1000.0]
    client = TestClient(_app(clock))
    for n in range(100):
        assert _post(client, f"198.51.100.{n}") == 200
    # A new IP is refused on this academy's host, but another host is fine.
    assert _post(client, "192.0.2.1") == 429
    assert _post(client, "192.0.2.1", host="lakeside-academy.courtmastr.test") == 200
    # Host variants (case, port, trailing dot) share the one bucket.
    assert _post(client, "192.0.2.2", host="Riverside-Academy.courtmastr.test.:443") == 429
    clock[0] += 601
    assert _post(client, "192.0.2.3") == 200


def test_a_blocked_ip_does_not_spend_the_host_budget() -> None:
    clock = [1000.0]
    client = TestClient(_app(clock))
    for _ in range(500):
        _post(client, "203.0.113.50")
    # Only its first 10 counted against the host: 90 more families fit.
    for n in range(90):
        assert _post(client, f"198.51.100.{n}") == 200
    assert _post(client, "198.51.100.200") == 429
