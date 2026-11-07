"""WhatsApp channel: invite-link parsing, the OpenWA adapter and sender gating.

The adapter is exercised over ``httpx.MockTransport``, so no test reaches a
real OpenWA instance. The builder tests pin the rule that only staging/prod, or
an explicit local allowlist, can ever hand a message to the real gateway.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.v2.composition.whatsapp import build_whatsapp_sender
from backend.v2.contexts.communications.domain.whatsapp import group_invite_code
from backend.v2.contexts.communications.infrastructure.openwa_send_port import (
    OpenWaWhatsAppSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_whatsapp_send_port import (
    SandboxWhatsAppSendPort,
    StubWhatsAppSendPort,
)

# --- invite links -------------------------------------------------------------


@pytest.mark.parametrize(
    ("link", "code"),
    [
        ("https://chat.whatsapp.com/ABC123", "ABC123"),
        ("https://chat.whatsapp.com/ABC123/", "ABC123"),
        ("https://chat.whatsapp.com/ABC123?mode=ac_t", "ABC123"),
        ("https://chat.whatsapp.com/invite/ABC123", "ABC123"),
        ("http://chat.whatsapp.com/ABC123", "ABC123"),
    ],
)
def test_group_invite_code_reads_whatsapp_invite_links(link: str, code: str) -> None:
    assert group_invite_code(link) == code


@pytest.mark.parametrize(
    "link",
    [None, "", "   ", "https://example.com/ABC123", "https://chat.whatsapp.com/", "not a url"],
)
def test_group_invite_code_rejects_anything_else(link: str | None) -> None:
    assert group_invite_code(link) is None


# --- OpenWA adapter -----------------------------------------------------------


def _adapter(handler) -> OpenWaWhatsAppSendPort:
    return OpenWaWhatsAppSendPort(
        base_url="http://openwa.test:2785/",
        api_key="op-key",
        session_id="sess-uuid",
        transport=httpx.MockTransport(handler),
    )


async def test_send_text_posts_to_the_session_with_the_api_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "m-1", "timestamp": 1})

    outcome = await _adapter(handler).send_text(chat_id="120363@g.us", text="hi")

    assert outcome.ok and outcome.provider_message_id == "m-1"
    [req] = seen
    assert str(req.url) == "http://openwa.test:2785/api/sessions/sess-uuid/messages/send-text"
    assert req.headers["X-API-Key"] == "op-key"
    assert json.loads(req.content) == {"chatId": "120363@g.us", "text": "hi"}


async def test_send_text_reads_a_wrapped_response() -> None:
    outcome = await _adapter(
        lambda _r: httpx.Response(201, json={"data": {"messageId": "m-2"}})
    ).send_text(chat_id="x@g.us", text="hi")

    assert outcome.provider_message_id == "m-2"


async def test_send_text_reports_http_errors_instead_of_raising() -> None:
    outcome = await _adapter(lambda _r: httpx.Response(503, json={})).send_text(
        chat_id="x@g.us", text="hi"
    )

    assert not outcome.ok
    assert outcome.failed_reason == "http_503"


async def test_send_text_reports_transport_errors_instead_of_raising() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    outcome = await _adapter(handler).send_text(chat_id="x@g.us", text="hi")

    assert not outcome.ok
    assert outcome.failed_reason == "unreachable"


async def test_resolve_group_uses_join_info() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "120363@g.us", "name": "Junior A"})

    assert await _adapter(handler).resolve_group("ABC123") == "120363@g.us"
    assert seen[0].url.path == "/api/sessions/sess-uuid/groups/join-info"
    assert seen[0].url.params["code"] == "ABC123"


async def test_resolve_group_returns_none_for_an_unknown_invite() -> None:
    adapter = _adapter(lambda _r: httpx.Response(404, json={}))

    assert await adapter.resolve_group("GONE") is None


# --- sandbox ------------------------------------------------------------------


async def test_sandbox_only_lets_allowlisted_chats_reach_the_real_gateway() -> None:
    real = StubWhatsAppSendPort()
    stub = StubWhatsAppSendPort()
    sandbox = SandboxWhatsAppSendPort(real=real, stub=stub, allowed_chats=frozenset({"ok@g.us"}))

    await sandbox.send_text(chat_id="ok@g.us", text="a")
    await sandbox.send_text(chat_id="real-class@g.us", text="b")

    assert [p["chat_id"] for p in real.sent] == ["ok@g.us"]
    assert [p["chat_id"] for p in stub.sent] == ["real-class@g.us"]


# --- builder ------------------------------------------------------------------


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "env": "dev",
        "whatsapp_delivery_enabled": True,
        "openwa_base_url": "http://openwa.test:2785",
        "openwa_api_key": "op-key",
        "openwa_session_id": "sess-uuid",
        "whatsapp_sandbox_chats": None,
        "tenancy_mode": "single_academy",
    }
    return SimpleNamespace(**{**base, **overrides})


def test_builder_refuses_multi_academy_mode() -> None:
    # One shared number + any pasted invite link = posting into another tenant's group.
    assert build_whatsapp_sender(_settings(env="prod", tenancy_mode="multi_academy")) is None


def test_builder_returns_none_when_whatsapp_is_off() -> None:
    assert build_whatsapp_sender(_settings(whatsapp_delivery_enabled=False)) is None


def test_builder_returns_none_when_openwa_is_not_configured() -> None:
    assert build_whatsapp_sender(_settings(openwa_api_key=None)) is None


def test_builder_uses_the_real_gateway_in_staging_and_prod() -> None:
    for env in ("staging", "prod"):
        assert isinstance(build_whatsapp_sender(_settings(env=env)), OpenWaWhatsAppSendPort)


def test_builder_stubs_dev_without_an_allowlist() -> None:
    assert isinstance(build_whatsapp_sender(_settings()), StubWhatsAppSendPort)


def test_builder_sandboxes_dev_with_an_allowlist() -> None:
    sender = build_whatsapp_sender(_settings(whatsapp_sandbox_chats=" a@g.us , b@g.us "))

    assert isinstance(sender, SandboxWhatsAppSendPort)
    assert sender.allowed_chats == frozenset({"a@g.us", "b@g.us"})


def test_builder_never_sandboxes_the_test_env() -> None:
    sender = build_whatsapp_sender(_settings(env="test", whatsapp_sandbox_chats="a@g.us"))

    assert isinstance(sender, StubWhatsAppSendPort)
