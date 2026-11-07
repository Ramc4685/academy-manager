"""Stub and sandbox WhatsApp send ports for local development and tests.

``StubWhatsAppSendPort`` records posts in memory and never contacts a gateway,
mirroring ``StubEmailSendPort``.

``SandboxWhatsAppSendPort`` is the one documented exception to "local never
calls a real provider" (``docs/agent/backend-api-rules.md``): in dev, posts to
chats on an explicit allowlist go to the real gateway so the owner can test
against a private group; every other chat goes to the stub. Group resolution
is a read-only preview and always uses the real gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.v2.contexts.communications.application.ports import SendOutcome, WhatsAppSendPort


@dataclass
class StubWhatsAppSendPort(WhatsAppSendPort):
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def resolve_group(self, invite_code: str) -> str | None:
        return f"stub-{invite_code}@g.us"

    async def send_text(self, *, chat_id: str, text: str) -> SendOutcome:
        record_id = f"stub-wa-{len(self.sent) + 1:06d}"
        self.sent.append({"provider_message_id": record_id, "chat_id": chat_id, "text": text})
        return SendOutcome(ok=True, provider_message_id=record_id, failed_reason=None)


@dataclass
class SandboxWhatsAppSendPort(WhatsAppSendPort):
    real: WhatsAppSendPort
    stub: WhatsAppSendPort
    allowed_chats: frozenset[str]

    async def resolve_group(self, invite_code: str) -> str | None:
        return await self.real.resolve_group(invite_code)

    async def send_text(self, *, chat_id: str, text: str) -> SendOutcome:
        target = self.real if chat_id in self.allowed_chats else self.stub
        return await target.send_text(chat_id=chat_id, text=text)
