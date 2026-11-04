"""Boot-time Resend credential validation (issue #435).

``ResendEmailSendPort.send`` swallows every exception into
``SendOutcome(ok=False)``, so an expired or revoked API key looked exactly like
a run of unlucky recipients and mail stopped silently. The boot probe exists to
turn that into one loud line on the deploy that broke it.

The hard part is *not* alerting when we shouldn't: Resend having a slow minute,
or DNS blipping during a deploy, must not be reported as "the key is dead", or
the alert stops being worth reading. So the probe has three outcomes, and these
tests pin all three.

No network: the Resend HTTP API is an ``httpx.MockTransport`` throughout, and
the key is a literal placeholder. The responses are the ones Resend returns
(``{"statusCode", "name", "message"}``), so these tests also pin that the
adapter maps them onto the same SDK exceptions as before.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from backend.v2.contexts.communications.infrastructure import resend_send_port
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)

Handler = Callable[[httpx.Request], Any]


def _port(handler: Handler) -> ResendEmailSendPort:
    return ResendEmailSendPort(
        api_key="re_test_key",
        from_address="noreply@example.test",
        transport=httpx.MockTransport(handler),
    )


def _error(status: int, name: str, message: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"statusCode": status, "name": name, "message": message})

    return handler


@pytest.mark.asyncio
async def test_a_working_key_validates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"object": "list", "data": []})

    check = await _port(handler).validate_credentials()

    assert check.ok is True
    assert not check.is_definitely_broken
    # The probe is the same read the SDK's ``Domains.list_async`` issued.
    [req] = requests
    assert req.method == "GET"
    assert str(req.url) == "https://api.resend.com/domains"
    assert req.headers["Authorization"] == "Bearer re_test_key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        _error(403, "invalid_api_key", "API key is invalid"),
        _error(401, "missing_api_key", "Missing API key in the authorization header"),
        _error(401, "unauthorized", "not authorized"),
        _error(403, "forbidden", "forbidden"),
    ],
)
async def test_a_rejected_key_is_definitely_broken(handler: Handler) -> None:
    check = await _port(handler).validate_credentials()

    assert check.ok is False
    assert check.is_definitely_broken
    assert check.detail


@pytest.mark.asyncio
async def test_a_send_scoped_key_is_valid_not_broken() -> None:
    """A sending-only key cannot list domains. It authenticated, which is the
    whole question — reporting it as dead would page someone every deploy."""
    check = await _port(
        _error(401, "restricted_api_key", "This API key is restricted to only send emails")
    ).validate_credentials()

    assert check.ok is True
    assert "restricted" in check.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        _error(500, "application_error", "something went wrong"),
        _error(502, "bad_gateway", "upstream"),
        lambda request: httpx.Response(503, text="<html>down</html>"),
    ],
)
async def test_a_provider_outage_is_undetermined_not_broken(handler: Handler) -> None:
    check = await _port(handler).validate_credentials()

    assert check.ok is None
    assert not check.is_definitely_broken


@pytest.mark.asyncio
async def test_a_transport_error_is_undetermined_not_broken() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns went away", request=request)

    check = await _port(handler).validate_credentials()

    assert check.ok is None
    assert not check.is_definitely_broken


@pytest.mark.asyncio
async def test_a_hanging_provider_times_out_as_undetermined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return httpx.Response(200, json={})

    monkeypatch.setattr(resend_send_port, "VALIDATION_TIMEOUT_SECONDS", 0.01)

    check = await _port(_hang).validate_credentials()

    assert check.ok is None
    assert "timed out" in check.detail


# ---------------------------------------------------------------------------
# The boot hook in main.py
# ---------------------------------------------------------------------------


class _Sender:
    def __init__(self, check: Any) -> None:
        self._check = check

    async def validate_credentials(self) -> Any:
        if isinstance(self._check, BaseException):
            raise self._check
        return self._check


@pytest.mark.asyncio
async def test_boot_alerts_only_on_a_definitely_broken_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.v2 import main as main_module
    from backend.v2.contexts.communications.infrastructure.resend_send_port import (
        CredentialCheck,
    )

    messages: list[str] = []
    monkeypatch.setattr(
        main_module, "capture_message", lambda msg, **_: messages.append(msg) or True
    )

    assert (
        await main_module._verify_email_credentials(
            _Sender(CredentialCheck(ok=False, detail="InvalidApiKeyError: nope"))
        )
        is False
    )
    assert len(messages) == 1

    assert (
        await main_module._verify_email_credentials(_Sender(CredentialCheck(ok=True, detail="ok")))
        is True
    )
    assert (
        await main_module._verify_email_credentials(
            _Sender(CredentialCheck(ok=None, detail="timed out after 10s"))
        )
        is None
    )
    assert len(messages) == 1, "an undetermined probe must not alert"


@pytest.mark.asyncio
async def test_boot_skips_a_port_with_nothing_to_validate() -> None:
    """The stub port used outside staging/prod has no credential, so local and
    test boots pay nothing for this check."""
    from backend.v2 import main as main_module
    from backend.v2.contexts.communications.infrastructure.stub_send_port import (
        StubEmailSendPort,
    )

    assert await main_module._verify_email_credentials(StubEmailSendPort()) is None


@pytest.mark.asyncio
async def test_boot_never_fails_when_the_probe_itself_raises() -> None:
    """A mail-provider problem must not stop the app from serving requests."""
    from backend.v2 import main as main_module

    assert await main_module._verify_email_credentials(_Sender(RuntimeError("boom"))) is None
