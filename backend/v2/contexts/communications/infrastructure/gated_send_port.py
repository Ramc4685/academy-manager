"""The one send-time gate seam.

Both the suppression list (#556) and recipient preferences (#555) hook in
here and nowhere else; no send loop performs its own check.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.send_gate import RecipientGate
from backend.v2.contexts.communications.domain.email_category import EmailCategory


@dataclass
class GatedEmailSendPort(EmailSendPort):
    """Decorator over any EmailSendPort that applies send-time gates.

    THE seam. Both the suppression list (#556) and recipient preferences (#555)
    hook in here and nowhere else; no send loop performs its own check.

    Order is deliberate: suppression is a deliverability/hard fact and is
    checked first, preferences second.
    """

    inner: EmailSendPort
    suppressions: RecipientGate | None = None  # #556
    preferences: RecipientGate | None = None  # #555

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
        if recipient.email:
            for gate in (self.suppressions, self.preferences):
                if gate is None:
                    continue
                verdict = await gate.check(
                    recipient_user_id=recipient.user_id,
                    email=recipient.email,
                    category=category,
                )
                if not verdict.allowed:
                    return SendOutcome(
                        ok=False,
                        provider_message_id=None,
                        failed_reason=verdict.reason or "blocked",
                        suppressed=True,
                    )
        return await self.inner.send(
            recipient=recipient,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            category=category,
        )
