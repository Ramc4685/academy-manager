"""Suite-wide guards shared by every v2 test."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from backend.v2.contexts.communications.infrastructure import resend_send_port


def _refuse_real_resend(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(
        f"tests must not call the real Resend API ({request.method} {request.url}); "
        "inject a transport into ResendEmailSendPort or monkeypatch "
        "resend_send_port.default_transport",
        request=request,
    )


@pytest.fixture(autouse=True)
def _no_real_resend_calls() -> Iterator[None]:
    """No test may reach api.resend.com.

    ``ResendEmailSendPort`` talks HTTP itself, so a port built by composition in
    a staging/prod-shaped test env would otherwise go to the network. Any port
    without an injected transport now fails the request (-> ``SendOutcome``
    not ok / probe undetermined) instead. Tests that want a response
    monkeypatch ``resend_send_port.default_transport`` over this.
    """
    previous = resend_send_port.default_transport
    resend_send_port.default_transport = httpx.MockTransport(_refuse_real_resend)
    try:
        yield
    finally:
        resend_send_port.default_transport = previous
