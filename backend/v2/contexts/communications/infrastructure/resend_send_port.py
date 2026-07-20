"""Resend-backed email send port.

Uses the `resend` SDK (already in venv). Only instantiated by composition
when APP_ENV=production (or staging) AND email_delivery_enabled=True.
All other environments use StubEmailSendPort.
"""

from __future__ import annotations

import asyncio

import resend

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)


class ResendEmailSendPort(EmailSendPort):
    def __init__(self, api_key: str, from_address: str) -> None:
        self._from_address = from_address
        resend.api_key = api_key

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> SendOutcome:
        if not recipient.email:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="no email address")
        try:
            params: resend.Emails.SendParams = {
                "from": self._from_address,
                "to": [recipient.email],
                "subject": subject,
                "html": body,
            }
            if cc:
                params["cc"] = cc
            if reply_to:
                params["reply_to"] = reply_to
            response = await asyncio.to_thread(resend.Emails.send, params)
            msg_id = response.get("id") if isinstance(response, dict) else str(response)
            return SendOutcome(ok=True, provider_message_id=msg_id, failed_reason=None)
        except Exception as exc:
            return SendOutcome(ok=False, provider_message_id=None, failed_reason=str(exc))
