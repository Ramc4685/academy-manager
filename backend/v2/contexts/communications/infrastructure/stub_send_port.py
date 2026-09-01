"""Stub email send port.

Records sends in memory. Use in local development, CI, and tests to satisfy
the rule in `docs/agent/backend-api-rules.md`: do not send real email from
local/test. The composition layer should select this adapter unless
`APP_ENV=production` and `EMAIL_DELIVERY_ENABLED=true`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass
class StubEmailSendPort(EmailSendPort):
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome:
        record_id = f"stub-{len(self.sent) + 1:06d}"
        self.sent.append(
            {
                "provider_message_id": record_id,
                "user_id": recipient.user_id,
                "email": recipient.email,
                "subject": subject,
                "body": body,
                "cc": list(cc) if cc else [],
                "bcc": list(bcc) if bcc else [],
                "reply_to": reply_to,
                "category": category,
            }
        )
        return SendOutcome(
            ok=True,
            provider_message_id=record_id,
            failed_reason=None,
        )
