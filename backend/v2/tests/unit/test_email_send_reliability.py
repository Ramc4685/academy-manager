"""L11 messaging reliability: provider idempotency keys, bounded retry,
the marketing sender and RFC 8058 one-click List-Unsubscribe headers.

No network: every request goes to an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.shared.comms.send_idempotency import (
    next_send_idempotency_key,
    send_idempotency_scope,
)


class _Script:
    """Answers each request with the next scripted response."""

    def __init__(self, *responses: Callable[[], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        make = self._responses.pop(0) if self._responses else _ok
        return make()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"id": "msg-1"})


def _status(code: int, name: str = "rate_limit_exceeded") -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(code, json={"statusCode": code, "name": name, "message": "x"})


class _Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _port(script: _Script, **kwargs: Any) -> ResendEmailSendPort:
    return ResendEmailSendPort(
        api_key="k",
        from_address="noreply@example.test",
        transport=script.transport(),
        **kwargs,
    )


def _recipient(email: str = "family@example.com") -> ResolvedRecipient:
    return ResolvedRecipient(user_id="u1", email=email)


def _who(email: str = "family@example.com") -> str:
    import hashlib

    return hashlib.sha256(email.encode()).hexdigest()[:16]


# -- idempotency keys ---------------------------------------------------------


async def test_sends_inside_a_scope_carry_per_recipient_keys() -> None:
    script = _Script()
    port = _port(script)
    with send_idempotency_scope("outbox:evt-1:handler"):
        await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
        await port.send(recipient=_recipient(), subject="b", body="<p>b</p>")
    await port.send(recipient=_recipient(), subject="c", body="<p>c</p>")

    keys = [r.headers.get("Idempotency-Key") for r in script.requests]
    assert keys == [f"outbox:evt-1:handler:{_who()}:1", f"outbox:evt-1:handler:{_who()}:2", None]


async def test_a_retry_in_a_different_order_keeps_each_familys_key() -> None:
    """Otherwise a reordered audience could hand family B family A's key and
    the provider would answer "already sent" for a mail B never got."""
    script = _Script()
    port = _port(script)
    for order in (["a@example.com", "b@example.com"], ["b@example.com", "a@example.com"]):
        with send_idempotency_scope("outbox:evt-5:h"):
            for email in order:
                await port.send(recipient=_recipient(email), subject="s", body="<p>s</p>")
    keys = [r.headers["Idempotency-Key"] for r in script.requests]
    assert keys[0] == keys[3] == f"outbox:evt-5:h:{_who('a@example.com')}:1"
    assert keys[1] == keys[2] == f"outbox:evt-5:h:{_who('b@example.com')}:1"
    assert "a@example.com" not in keys[0]


async def test_a_replayed_scope_mints_the_same_keys() -> None:
    """The point of the key: an outbox retry of a half-done event re-sends with
    the keys of its first run, so the provider drops what already went out."""
    script = _Script()
    port = _port(script)
    for _ in range(2):
        with send_idempotency_scope("outbox:evt-9:h"):
            await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert [r.headers["Idempotency-Key"] for r in script.requests] == [
        f"outbox:evt-9:h:{_who()}:1",
        f"outbox:evt-9:h:{_who()}:1",
    ]


def test_scopes_nest_and_restore() -> None:
    assert next_send_idempotency_key("a@example.com") is None
    with send_idempotency_scope("outer"):
        with send_idempotency_scope("inner"):
            assert (next_send_idempotency_key("a@example.com") or "").startswith("inner:")
        assert (next_send_idempotency_key("a@example.com") or "").startswith("outer:")
    assert next_send_idempotency_key("a@example.com") is None


async def test_a_keyed_conflict_is_a_failure_and_is_not_retried() -> None:
    """Resend's invalid_idempotent_request means the key was reused with a
    different payload, not that this mail went out: report it failed so the
    outbox ladder and dead letter see it."""
    script = _Script(_status(409, "invalid_idempotent_request"), _ok)
    port = _port(script, max_retries=2, sleep=_Sleeps())
    with send_idempotency_scope("outbox:evt-2:h"):
        outcome = await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert outcome.ok is False
    assert len(script.requests) == 1


async def test_conflict_without_a_key_is_still_a_failure() -> None:
    script = _Script(_status(409, "invalid_idempotent_request"))
    outcome = await _port(script).send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert outcome.ok is False


# -- bounded retry ------------------------------------------------------------


async def test_default_port_does_not_retry() -> None:
    """Today's behaviour unless EMAIL_SEND_MAX_RETRIES is set."""
    script = _Script(_status(429))
    sleeps = _Sleeps()
    outcome = await _port(script, sleep=sleeps).send(
        recipient=_recipient(), subject="a", body="<p>a</p>"
    )
    assert outcome.ok is False
    assert len(script.requests) == 1
    assert sleeps.calls == []


async def test_rate_limit_is_retried_with_backoff() -> None:
    script = _Script(_status(429), _status(429), _ok)
    sleeps = _Sleeps()
    port = _port(script, max_retries=2, retry_base_delay=0.5, sleep=sleeps)
    outcome = await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert outcome.ok is True
    assert len(script.requests) == 3
    assert sleeps.calls == [0.5, 1.0]


@pytest.mark.parametrize("name", ["daily_quota_exceeded", "monthly_quota_exceeded"])
async def test_a_quota_429_is_not_retried(name: str) -> None:
    script = _Script(_status(429, name), _ok)
    sleeps = _Sleeps()
    port = _port(script, max_retries=2, sleep=sleeps)
    outcome = await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert outcome.ok is False
    assert len(script.requests) == 1
    assert sleeps.calls == []


async def test_retries_are_bounded() -> None:
    script = _Script(_status(429), _status(429), _status(429), _ok)
    port = _port(script, max_retries=2, sleep=_Sleeps())
    outcome = await port.send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert outcome.ok is False
    assert len(script.requests) == 3


async def test_server_error_is_retried_only_with_an_idempotency_key() -> None:
    """A 5xx may have sent the mail; re-sending without a key could double it."""
    unkeyed = _Script(_status(500, "internal_server_error"), _ok)
    outcome = await _port(unkeyed, max_retries=2, sleep=_Sleeps()).send(
        recipient=_recipient(), subject="a", body="<p>a</p>"
    )
    assert outcome.ok is False
    assert len(unkeyed.requests) == 1

    keyed = _Script(_status(503, "internal_server_error"), _ok)
    with send_idempotency_scope("outbox:evt-3:h"):
        outcome = await _port(keyed, max_retries=2, sleep=_Sleeps()).send(
            recipient=_recipient(), subject="a", body="<p>a</p>"
        )
    assert outcome.ok is True
    assert [r.headers["Idempotency-Key"] for r in keyed.requests] == [
        f"outbox:evt-3:h:{_who()}:1",
        f"outbox:evt-3:h:{_who()}:1",
    ]


async def test_client_errors_are_never_retried() -> None:
    script = _Script(_status(422, "validation_error"), _ok)
    with send_idempotency_scope("s"):
        outcome = await _port(script, max_retries=3, sleep=_Sleeps()).send(
            recipient=_recipient(), subject="a", body="<p>a</p>"
        )
    assert outcome.ok is False
    assert len(script.requests) == 1


# -- marketing sender + one-click unsubscribe ---------------------------------


async def test_campaign_mail_uses_the_marketing_sender_when_set() -> None:
    script = _Script()
    port = _port(script, marketing_from_address="news@mail.example.test")
    await port.send(
        recipient=_recipient(),
        subject="a",
        body="<p>a</p>",
        category=EmailCategory.CAMPAIGN,
        sender_name="Synthetic Academy",
    )
    await port.send(recipient=_recipient(), subject="b", body="<p>b</p>")
    froms = [json.loads(r.content)["from"] for r in script.requests]
    assert froms == ["Synthetic Academy <news@mail.example.test>", "noreply@example.test"]


async def test_campaign_mail_keeps_the_platform_sender_without_the_setting() -> None:
    script = _Script()
    await _port(script).send(
        recipient=_recipient(), subject="a", body="<p>a</p>", category=EmailCategory.CAMPAIGN
    )
    assert json.loads(script.requests[0].content)["from"] == "noreply@example.test"


async def test_unsubscribe_url_becomes_rfc8058_headers() -> None:
    script = _Script()
    await _port(script).send(
        recipient=_recipient(),
        subject="a",
        body="<p>a</p>",
        category=EmailCategory.CAMPAIGN,
        unsubscribe_url="https://club.example.test/api/v2/unsubscribe/one-click?t=abc",
    )
    body = json.loads(script.requests[0].content)
    assert body["headers"] == {
        "List-Unsubscribe": "<https://club.example.test/api/v2/unsubscribe/one-click?t=abc>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


async def test_no_unsubscribe_url_means_no_headers_field() -> None:
    script = _Script()
    await _port(script).send(recipient=_recipient(), subject="a", body="<p>a</p>")
    assert "headers" not in json.loads(script.requests[0].content)


# -- the outbox dispatcher opens a scope per handler run ------------------------


async def test_dispatcher_runs_each_handler_inside_an_event_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mongomock_motor import AsyncMongoMockClient  # type: ignore[import-not-found]

    from backend.v2.shared.events import dispatcher as module
    from backend.v2.shared.events.base import DomainEvent

    seen: list[str | None] = []

    async def handler_fn(event: DomainEvent) -> None:
        key = next_send_idempotency_key("a@example.com")
        seen.append(key.rsplit(":", 2)[0] if key else None)

    monkeypatch.setattr(module, "_reconstruct_event", lambda doc, cls: object())
    disp = module.EventDispatcher(AsyncMongoMockClient()["l11"])
    doc = {"event_id": "evt-42", "name": "Test.L11Scope", "schema_version": 1}
    ok = await disp._run_handler_with_retries(doc, "notify_parent", handler_fn, DomainEvent)
    assert ok is True
    assert seen == ["outbox:evt-42:notify_parent"]
    assert next_send_idempotency_key("a@example.com") is None
