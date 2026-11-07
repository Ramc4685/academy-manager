"""OpenWA WhatsApp send port.

OpenWA (github.com/rmyndharis/OpenWA) is a self-hosted gateway that drives a
linked WhatsApp device. It is unofficial: the linked number can be restricted
by WhatsApp, which is why every caller treats this channel as best-effort and
why the adapter is only ever built by ``composition.whatsapp`` (pinned by
``tests/structural/test_whatsapp_sender_construction.py``).

The key must be an OpenWA *operator* key scoped to the one session, never the
admin key. Failures come back as ``SendOutcome(ok=False)``; nothing here raises
on an HTTP or network error.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend.v2.contexts.communications.application.ports import SendOutcome, WhatsAppSendPort

logger = logging.getLogger(__name__)

#: Short on purpose: the urgent fan-out awaits this after email, and a hung
#: gateway must not hold the admin's request open.
DEFAULT_TIMEOUT_SECONDS = 5.0


def _payload(response: httpx.Response) -> dict[str, Any]:
    """OpenWA answers either bare or wrapped in ``{"data": …}``."""
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    data = body.get("data")
    return data if isinstance(data, dict) else body


class OpenWaWhatsAppSendPort(WhatsAppSendPort):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session_id: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/api/sessions/{session_id}"
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, transport=self._transport
        )

    async def resolve_group(self, invite_code: str) -> str | None:
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self._base}/groups/join-info", params={"code": invite_code}
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "whatsapp.resolve_group_unreachable", extra={"error": type(exc).__name__}
            )
            return None
        if response.status_code != 200:
            logger.warning("whatsapp.resolve_group_failed", extra={"status": response.status_code})
            return None
        group_id = _payload(response).get("id")
        return str(group_id) if group_id else None

    async def send_text(self, *, chat_id: str, text: str) -> SendOutcome:
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base}/messages/send-text", json={"chatId": chat_id, "text": text}
                )
        except httpx.HTTPError as exc:
            logger.warning("whatsapp.send_unreachable", extra={"error": type(exc).__name__})
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="unreachable")
        if response.status_code >= 400:
            logger.warning("whatsapp.send_failed", extra={"status": response.status_code})
            return SendOutcome(
                ok=False, provider_message_id=None, failed_reason=f"http_{response.status_code}"
            )
        message_id = _payload(response).get("messageId")
        return SendOutcome(
            ok=True, provider_message_id=str(message_id) if message_id else None, failed_reason=None
        )
