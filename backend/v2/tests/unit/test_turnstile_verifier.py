"""Turnstile fails closed when configured and is skipped when not (L9)."""

from __future__ import annotations

from typing import Any

import httpx

from backend.v2.shared.http.turnstile import SITEVERIFY_URL, TurnstileVerifier


def _verifier(handler: Any) -> TurnstileVerifier:
    return TurnstileVerifier(
        "secret-test",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_skipped_without_a_secret() -> None:
    assert await TurnstileVerifier(None).verify(None, remote_ip=None) is True
    assert await TurnstileVerifier("  ").verify("", remote_ip=None) is True


async def test_a_good_token_passes_and_sends_secret_token_and_ip() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True})

    assert await _verifier(handler).verify("tok-1", remote_ip="203.0.113.9") is True
    [request] = seen
    assert str(request.url) == SITEVERIFY_URL
    body = request.content.decode()
    assert "secret=secret-test" in body and "response=tok-1" in body
    assert "remoteip=203.0.113.9" in body


async def test_fails_closed_on_refusal_error_outage_and_missing_token() -> None:
    def refused(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error-codes": ["invalid"]})

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    def not_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    for handler in (refused, broken, down, not_json):
        assert await _verifier(handler).verify("tok", remote_ip=None) is False
    ok = _verifier(lambda _r: httpx.Response(200, json={"success": True}))
    assert await ok.verify(None, remote_ip=None) is False
    assert await ok.verify("x" * 2049, remote_ip=None) is False
