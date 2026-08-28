"""Boot-time Resend credential validation (issue #435).

``ResendEmailSendPort.send`` swallows every exception into
``SendOutcome(ok=False)``, so an expired or revoked API key looked exactly like
a run of unlucky recipients and mail stopped silently. The boot probe exists to
turn that into one loud line on the deploy that broke it.

The hard part is *not* alerting when we shouldn't: Resend having a slow minute,
or DNS blipping during a deploy, must not be reported as "the key is dead", or
the alert stops being worth reading. So the probe has three outcomes, and these
tests pin all three.

No network: ``resend.Domains.list_async`` is monkeypatched throughout, and the
key is a literal placeholder.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import resend
from resend.exceptions import InvalidApiKeyError, MissingApiKeyError, ResendError

from backend.v2.contexts.communications.infrastructure import resend_send_port
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)


def _port() -> ResendEmailSendPort:
    return ResendEmailSendPort(api_key="re_test_key", from_address="noreply@example.test")


def _patch_probe(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> None:
    """Make the domains probe return, or raise, ``outcome``."""

    async def _fake_list(*args: Any, **kwargs: Any) -> Any:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(resend.Domains, "list_async", _fake_list)


@pytest.mark.asyncio
async def test_a_working_key_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, {"data": []})

    check = await _port().validate_credentials()

    assert check.ok is True
    assert not check.is_definitely_broken


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        InvalidApiKeyError(message="API key is invalid", error_type="invalid_api_key", code="403"),
        MissingApiKeyError(message="missing", error_type="missing_api_key", code="401"),
    ],
)
async def test_a_rejected_key_is_definitely_broken(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    _patch_probe(monkeypatch, exc)

    check = await _port().validate_credentials()

    assert check.ok is False
    assert check.is_definitely_broken
    assert check.detail


@pytest.mark.asyncio
async def test_a_send_scoped_key_is_valid_not_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sending-only key cannot list domains. It authenticated, which is the
    whole question — reporting it as dead would page someone every deploy."""
    _patch_probe(
        monkeypatch,
        ResendError(
            code="401",
            error_type="restricted_api_key",
            message="This API key is restricted to only send emails",
            suggested_action="use a full access key",
        ),
    )

    check = await _port().validate_credentials()

    assert check.ok is True
    assert "restricted" in check.detail


@pytest.mark.asyncio
async def test_a_provider_outage_is_undetermined_not_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(
        monkeypatch,
        ResendError(
            code="500",
            error_type="application_error",
            message="something went wrong",
            suggested_action="retry",
        ),
    )

    check = await _port().validate_credentials()

    assert check.ok is None
    assert not check.is_definitely_broken


@pytest.mark.asyncio
async def test_a_transport_error_is_undetermined_not_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(monkeypatch, ConnectionError("dns went away"))

    check = await _port().validate_credentials()

    assert check.ok is None
    assert not check.is_definitely_broken


@pytest.mark.asyncio
async def test_a_hanging_provider_times_out_as_undetermined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _hang(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(60)

    monkeypatch.setattr(resend.Domains, "list_async", _hang)
    monkeypatch.setattr(resend_send_port, "VALIDATION_TIMEOUT_SECONDS", 0.01)

    check = await _port().validate_credentials()

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
