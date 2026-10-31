"""Each ``ResendEmailSendPort`` sends with its OWN API key.

The resend SDK authenticates every request with the module-global
``resend.api_key``. The adapter used to assign that global in ``__init__``, so
two ports with different keys (one per academy, once academies bring their own
Resend account) would both send with whichever key was set last — one tenant's
mail authenticated as another tenant. The adapter now makes the HTTP call
itself with the instance key and never touches the global.

These tests also pin that BLNO's production request is unchanged: same URL,
same headers, same JSON body, same From address.

No network: every request goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import resend
from resend.version import get_version

from backend.v2.composition.digests import _build_email_sender
from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.infrastructure import resend_send_port
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.shared.comms.email_theme import html_to_text
from backend.v2.shared.config.settings import Settings

_PROD_FRONTEND = "https://academy.courtmastr.com"


class _Recorder:
    """A mock Resend API that records each request and answers with an id."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.requests: list[httpx.Request] = []
        self._delay = delay

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        return httpx.Response(200, json={"id": f"msg-{len(self.requests)}"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _recipient(email: str = "family@example.com") -> ResolvedRecipient:
    return ResolvedRecipient(user_id="u1", email=email)


# -- (b) concurrent ports never share a key ----------------------------------


@pytest.mark.asyncio
async def test_two_ports_sending_concurrently_each_use_their_own_key() -> None:
    """On the old adapter both requests carried ``Bearer re_key_B``."""
    recorder = _Recorder(delay=0.01)
    port_a = ResendEmailSendPort(
        api_key="re_key_A", from_address="a@example.test", transport=recorder.transport()
    )
    port_b = ResendEmailSendPort(
        api_key="re_key_B", from_address="b@example.test", transport=recorder.transport()
    )

    outcomes = await asyncio.gather(
        port_a.send(recipient=_recipient(), subject="from A", body="<p>a</p>"),
        port_b.send(recipient=_recipient(), subject="from B", body="<p>b</p>"),
        port_a.send(recipient=_recipient(), subject="from A", body="<p>a2</p>"),
    )

    assert all(o.ok for o in outcomes)
    by_subject: dict[str, set[str]] = {}
    for req in recorder.requests:
        body = json.loads(req.content)
        by_subject.setdefault(body["subject"], set()).add(req.headers["Authorization"])
    assert by_subject == {"from A": {"Bearer re_key_A"}, "from B": {"Bearer re_key_B"}}


@pytest.mark.asyncio
async def test_ports_built_by_composition_do_not_share_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same property through the ``default_transport`` seam composition uses."""
    recorder = _Recorder()
    monkeypatch.setattr(resend_send_port, "default_transport", recorder.transport())
    first = ResendEmailSendPort(api_key="re_first", from_address="x@example.test")
    second = ResendEmailSendPort(api_key="re_second", from_address="x@example.test")

    await first.send(recipient=_recipient(), subject="1", body="<p>1</p>")
    await second.send(recipient=_recipient(), subject="2", body="<p>2</p>")
    await first.send(recipient=_recipient(), subject="3", body="<p>3</p>")

    assert [r.headers["Authorization"] for r in recorder.requests] == [
        "Bearer re_first",
        "Bearer re_second",
        "Bearer re_first",
    ]


# -- (c) the SDK global is never read or written ------------------------------


@pytest.mark.asyncio
async def test_the_sdk_global_api_key_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "re_global_sentinel_must_not_change"
    monkeypatch.setattr(resend, "api_key", sentinel)
    recorder = _Recorder()

    port = ResendEmailSendPort(
        api_key="re_instance", from_address="a@example.test", transport=recorder.transport()
    )
    assert resend.api_key == sentinel
    await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    await port.validate_credentials()

    assert resend.api_key == sentinel
    # ...and the global is not what authenticates the request either.
    assert {r.headers["Authorization"] for r in recorder.requests} == {"Bearer re_instance"}


# -- (a) BLNO's production request is unchanged ------------------------------


def _prod_settings(monkeypatch: pytest.MonkeyPatch, *, sender_email: str | None) -> Settings:
    """The backend/fly.toml [env] block plus the secrets prod validation needs."""
    for name in (
        "V2_ENV",
        "APP_ENV",
        "V2_SENDER_EMAIL",
        "SENDER_EMAIL",
        "V2_FRONTEND_URL",
        "FRONTEND_URL",
        "EMAIL_DELIVERY_ENABLED",
        "V2_EMAIL_DELIVERY_ENABLED",
        "V2_CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("V2_ENV", "prod")
    monkeypatch.setenv("DB_NAME", "academy_manager")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://prod.example.test")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("V2_EMAIL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_URL", _PROD_FRONTEND)
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://academy.courtmastr.com,https://blno-academy.courtmastr.com"
    )
    monkeypatch.setenv("APP_TENANCY_MODE", "single_academy")
    monkeypatch.setenv("PRIMARY_ACADEMY_ID", "acad_blno_badminton")
    monkeypatch.setenv("ENABLE_PLATFORM_ROUTES", "false")
    monkeypatch.setenv("ENABLE_OWNER_ROLE", "false")
    monkeypatch.setenv("V2_STRIPE_USE_FAKE_GATEWAY", "false")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("V2_RESEND_API_KEY", "re_blno_platform_key")
    if sender_email is not None:
        monkeypatch.setenv("SENDER_EMAIL", sender_email)
    return Settings(_env_file=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender_email", "expected_address"),
    [
        (None, "noreply@academy.courtmastr.com"),
        ("hello@courtmastr.com", "hello@courtmastr.com"),
    ],
)
async def test_prod_composed_sender_sends_the_same_request_as_before(
    monkeypatch: pytest.MonkeyPatch, sender_email: str | None, expected_address: str
) -> None:
    settings = _prod_settings(monkeypatch, sender_email=sender_email)
    assert settings.env == "prod"
    assert settings.resolved_sender_email() == expected_address
    recorder = _Recorder()
    monkeypatch.setattr(resend_send_port, "default_transport", recorder.transport())

    port = _build_email_sender(settings)  # no db -> the bare adapter
    assert isinstance(port, ResendEmailSendPort)

    html = '<p>Hi <a href="https://academy.courtmastr.com/pay">Pay</a></p>'
    outcome = await port.send(
        recipient=_recipient("parent@example.com"),
        subject="Invoice ready",
        body=html,
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
        reply_to="desk@example.com",
        sender_name="BLNO Badminton",
    )

    assert outcome.ok is True
    assert outcome.provider_message_id == "msg-1"
    [req] = recorder.requests
    assert req.method == "POST"
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["Authorization"] == "Bearer re_blno_platform_key"
    assert req.headers["Accept"] == "application/json"
    assert req.headers["User-Agent"] == f"resend-python:{get_version()}"
    assert req.headers["Content-Type"] == "application/json"
    assert "Idempotency-Key" not in req.headers
    assert json.loads(req.content) == {
        "from": f"BLNO Badminton <{expected_address}>",
        "to": ["parent@example.com"],
        "subject": "Invoice ready",
        "html": html,
        "text": html_to_text(html),
        "cc": ["cc@example.com"],
        "bcc": ["bcc@example.com"],
        "reply_to": "desk@example.com",
    }


@pytest.mark.asyncio
async def test_optional_fields_are_omitted_when_unset() -> None:
    recorder = _Recorder()
    port = ResendEmailSendPort(
        api_key="k", from_address="noreply@example.test", transport=recorder.transport()
    )
    await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    body = json.loads(recorder.requests[0].content)
    assert body["from"] == "noreply@example.test"
    assert not {"cc", "bcc", "reply_to"} & body.keys()


# -- send error semantics -----------------------------------------------------


def _answer(status: int, payload: Any) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


@pytest.mark.asyncio
async def test_an_api_rejection_is_a_failed_outcome_not_an_exception() -> None:
    port = ResendEmailSendPort(
        api_key="k",
        from_address="a@example.test",
        transport=_answer(
            422, {"statusCode": 422, "name": "validation_error", "message": "bad to"}
        ),
    )
    outcome = await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    assert outcome.ok is False
    assert outcome.failed_reason == "bad to"


@pytest.mark.asyncio
async def test_a_dead_key_is_a_failed_outcome_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    port = ResendEmailSendPort(
        api_key="re_dead",
        from_address="a@example.test",
        transport=_answer(
            403, {"statusCode": 403, "name": "invalid_api_key", "message": "API key is invalid"}
        ),
    )
    with caplog.at_level("ERROR"):
        outcome = await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    assert outcome.ok is False
    assert "resend_send_rejected_credentials" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", None])
async def test_a_missing_key_fails_like_the_sdk_without_a_request(key: str | None) -> None:
    recorder = _Recorder()
    port = ResendEmailSendPort(
        api_key=key, from_address="a@example.test", transport=recorder.transport()
    )
    outcome = await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    check = await port.validate_credentials()
    assert outcome.ok is False
    assert "Missing API key" in (outcome.failed_reason or "")
    assert check.ok is False
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_a_transport_failure_is_a_failed_outcome() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns went away", request=request)

    port = ResendEmailSendPort(
        api_key="k", from_address="a@example.test", transport=httpx.MockTransport(_boom)
    )
    outcome = await port.send(recipient=_recipient(), subject="s", body="<p>b</p>")
    assert outcome.ok is False
    assert "dns went away" in (outcome.failed_reason or "")
