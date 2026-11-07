"""The single construction site for the WhatsApp send port.

Same rule as ``digests._build_email_sender``: the real gateway is only wired in
staging/prod. The one addition is the local sandbox: in ``dev``, a non-empty
``whatsapp_sandbox_chats`` allowlist lets posts to those chats reach the real
gateway (a private test group), and everything else goes to the stub. ``test``
never sandboxes. Pinned by ``tests/structural/test_whatsapp_sender_construction.py``.

Returns ``None`` when the channel is off or OpenWA is not configured, which the
announcement service reads as "skip WhatsApp".
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.communications.application.ports import WhatsAppSendPort
from backend.v2.contexts.communications.infrastructure.openwa_send_port import (
    OpenWaWhatsAppSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_whatsapp_send_port import (
    SandboxWhatsAppSendPort,
    StubWhatsAppSendPort,
)

_REAL_WHATSAPP_ENVS = frozenset({"staging", "prod"})


def _allowlist(raw: str | None) -> frozenset[str]:
    return frozenset(chat.strip() for chat in (raw or "").split(",") if chat.strip())


def build_whatsapp_sender(settings: Any) -> WhatsAppSendPort | None:
    base_url = getattr(settings, "openwa_base_url", None)
    api_key = getattr(settings, "openwa_api_key", None)
    session_id = getattr(settings, "openwa_session_id", None)
    if not (
        getattr(settings, "whatsapp_delivery_enabled", False)
        and base_url
        and api_key
        and session_id
    ):
        return None
    # One linked number posts for every academy, and any invite link an admin
    # pastes resolves, so nothing ties a group to its tenant. Single-academy only
    # until there is a session per academy (prd.md, phase 5+).
    if getattr(settings, "tenancy_mode", "single_academy") != "single_academy":
        return None
    env = str(getattr(settings, "env", "") or "").lower()
    if env in _REAL_WHATSAPP_ENVS:
        return OpenWaWhatsAppSendPort(base_url=base_url, api_key=api_key, session_id=session_id)
    allowed = _allowlist(getattr(settings, "whatsapp_sandbox_chats", None))
    if env == "dev" and allowed:
        return SandboxWhatsAppSendPort(
            real=OpenWaWhatsAppSendPort(base_url=base_url, api_key=api_key, session_id=session_id),
            stub=StubWhatsAppSendPort(),
            allowed_chats=allowed,
        )
    return StubWhatsAppSendPort()
