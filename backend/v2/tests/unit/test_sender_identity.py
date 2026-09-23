"""Per-academy sender display name + reply-to (roadmap L9a)."""

from __future__ import annotations

from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure import resend_send_port
from backend.v2.contexts.communications.infrastructure.gated_send_port import GatedEmailSendPort
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.shared.comms.sender_identity import (
    REPLY_TO_MAX_LENGTH,
    InvalidSenderValue,
    SenderIdentity,
    format_from_header,
    resolve_sender,
    sender_identity_for_current_academy,
    validate_reply_to,
    validate_sender_name,
)
from backend.v2.shared.tenancy import tenant_scope

PLATFORM = "noreply@platform.example"


# -- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "Club\r\nBcc: attacker@example.com",
        "Club\nX-Injected: yes",
        "Club\rX",
        "Club\x00",
        "Club <attacker@example.com>",
        "Club >",
        "x" * 81,
    ],
)
def test_sender_name_rejects_header_injection_and_overlong(bad: str) -> None:
    with pytest.raises(InvalidSenderValue):
        validate_sender_name(bad)


def test_sender_name_trims_and_blank_clears() -> None:
    assert validate_sender_name("  Synthetic Shuttle Club  ") == "Synthetic Shuttle Club"
    assert validate_sender_name("   ") is None
    assert validate_sender_name(None) is None
    assert validate_sender_name("x" * 80) == "x" * 80


@pytest.mark.parametrize(
    "bad", ["not-an-email", "a@", "desk@example.com\r\nBcc: attacker@example.com"]
)
def test_reply_to_rejects_invalid(bad: str) -> None:
    with pytest.raises(InvalidSenderValue):
        validate_reply_to(bad)


def test_reply_to_rejects_over_length() -> None:
    local = "a" * 64
    domain = ".".join(["b" * 60] * 4) + ".com"
    too_long = f"{local}@{domain}"
    assert len(too_long) > REPLY_TO_MAX_LENGTH
    with pytest.raises(InvalidSenderValue):
        validate_reply_to(too_long)


def test_reply_to_trims_and_blank_clears() -> None:
    assert validate_reply_to(" desk@example.com ") == "desk@example.com"
    assert validate_reply_to("") is None


# -- resolve_sender ----------------------------------------------------------


def test_resolve_sender_prefers_explicit_name_and_reply_to() -> None:
    identity = resolve_sender(
        {
            "display_name": "Synthetic Academy",
            "email_sender_name": "Synthetic Front Desk",
            "email_reply_to": "desk@example.com",
        }
    )
    assert identity == SenderIdentity(
        sender_name="Synthetic Front Desk", reply_to="desk@example.com"
    )


def test_resolve_sender_falls_back_to_academy_name_and_no_reply_to() -> None:
    assert resolve_sender({"display_name": "Synthetic Academy"}) == SenderIdentity(
        sender_name="Synthetic Academy", reply_to=None
    )
    assert resolve_sender({"name": "Legacy Name"}).sender_name == "Legacy Name"


def test_resolve_sender_with_nothing_keeps_the_old_behaviour() -> None:
    assert resolve_sender(None) == SenderIdentity()
    assert resolve_sender({}) == SenderIdentity()


def test_resolve_sender_ignores_unsafe_stored_values() -> None:
    """A document edited by hand (or predating validation) cannot inject."""
    identity = resolve_sender(
        {
            "display_name": "Synthetic Academy",
            "email_sender_name": "Evil\r\nBcc: attacker@example.com",
            "email_reply_to": "nope",
        }
    )
    assert identity == SenderIdentity(sender_name="Synthetic Academy", reply_to=None)


# -- From header -------------------------------------------------------------


def test_from_header_keeps_the_platform_address() -> None:
    header = format_from_header("Synthetic Academy", PLATFORM)
    assert header == f"Synthetic Academy <{PLATFORM}>"
    assert parseaddr(header)[1] == PLATFORM


def test_from_header_without_a_name_is_unchanged() -> None:
    assert format_from_header(None, PLATFORM) == PLATFORM
    assert format_from_header("", PLATFORM) == PLATFORM
    assert format_from_header("Bad\r\nName", PLATFORM) == PLATFORM


def test_from_header_encodes_unicode_names() -> None:
    header = format_from_header("Club Élan 羽毛球", PLATFORM)
    assert header.isascii()
    name, address = parseaddr(header)
    assert address == PLATFORM
    assert str(make_header(decode_header(name))) == "Club Élan 羽毛球"


def test_from_header_quotes_specials() -> None:
    header = format_from_header('Smith, Jones "Club"', PLATFORM)
    name, address = parseaddr(header)
    assert (name, address) == ('Smith, Jones "Club"', PLATFORM)


def test_from_header_replaces_a_configured_platform_display_name() -> None:
    header = format_from_header("Synthetic Academy", f"Platform <{PLATFORM}>")
    assert header == f"Synthetic Academy <{PLATFORM}>"


# -- adapters ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_resend_adapter_sends_academy_name_on_platform_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_send(params: dict[str, Any]) -> dict[str, str]:
        captured.append(params)
        return {"id": "msg-1"}

    monkeypatch.setattr(resend_send_port.resend.Emails, "send", fake_send)
    port = ResendEmailSendPort(api_key="re_test", from_address=PLATFORM)
    recipient = ResolvedRecipient(user_id="u1", email="family@example.com")

    await port.send(
        recipient=recipient,
        subject="s",
        body="<p>b</p>",
        reply_to="desk@example.com",
        sender_name="Synthetic Academy",
    )
    await port.send(recipient=recipient, subject="s", body="<p>b</p>")

    assert captured[0]["from"] == f"Synthetic Academy <{PLATFORM}>"
    assert captured[0]["reply_to"] == "desk@example.com"
    assert captured[1]["from"] == PLATFORM
    assert "reply_to" not in captured[1]


@pytest.mark.asyncio
async def test_gated_port_forwards_sender_name() -> None:
    inner = StubEmailSendPort()
    gated = GatedEmailSendPort(inner=inner)
    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email="family@example.com"),
        subject="s",
        body="b",
        category=EmailCategory.TRANSACTIONAL,
        sender_name="Synthetic Academy",
    )
    assert isinstance(outcome, SendOutcome) and outcome.ok
    assert inner.sent[0]["sender_name"] == "Synthetic Academy"


# -- tenant-scoped lookup ----------------------------------------------------


class _KeyedAcademies:
    """Mirrors ``MongoAcademyRepository.find_by_id``: keyed by academy id."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self.docs = docs
        self.calls: list[str] = []

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        self.calls.append(academy_id)
        return self.docs.get(academy_id)


@pytest.mark.asyncio
async def test_current_academy_lookup_never_uses_another_tenant() -> None:
    academies = _KeyedAcademies(
        {
            "acad-a": {"display_name": "Alpha Shuttle Club", "email_reply_to": "a@example.com"},
            "acad-b": {"display_name": "Bravo Racquet Club", "email_reply_to": "b@example.com"},
        }
    )
    with tenant_scope("acad-a"):
        a = await sender_identity_for_current_academy(academies)
    with tenant_scope("acad-b"):
        b = await sender_identity_for_current_academy(academies)

    assert a == SenderIdentity(sender_name="Alpha Shuttle Club", reply_to="a@example.com")
    assert b == SenderIdentity(sender_name="Bravo Racquet Club", reply_to="b@example.com")
    assert academies.calls == ["acad-a", "acad-b"]


@pytest.mark.asyncio
async def test_current_academy_lookup_degrades_to_empty_identity() -> None:
    class Broken:
        async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
            raise RuntimeError("db down")

    with tenant_scope("acad-a"):
        assert await sender_identity_for_current_academy(Broken()) == SenderIdentity()
        assert await sender_identity_for_current_academy(None) == SenderIdentity()
    # No tenant in context at all: still no exception, still no identity.
    assert await sender_identity_for_current_academy(_KeyedAcademies({})) == SenderIdentity()
