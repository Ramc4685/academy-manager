"""GatedEmailSendPort — the one place send-time gates are applied.

THE seam. Both the recipient's unsubscribe preferences (#555) and the provider
suppression list (#556) hook in here and nowhere else; no send loop performs
its own check, so a new send path cannot forget one. Wrapping (rather than
editing each send loop) is what makes "every send path checks both gates" true
by construction instead of by review.

Order is deliberate: suppression is a deliverability/hard fact about the
mailbox and is checked first; preferences — a choice about content — second.

This decorator is not ``ResendEmailSendPort``; it wraps whatever
``composition.digests._build_email_sender`` produced, so the staging/prod env
gate enforced by ``tests/structural/test_email_sender_construction.py`` is
untouched. The stub is wrapped too, so the gates are exercised in dev and CI
rather than only in production.
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
    """Decorator over any EmailSendPort that applies the send-time gates."""

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
