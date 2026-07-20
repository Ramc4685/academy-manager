"""SendParentDailyDigest use case.

The parent-facing sibling of :class:`SendCoachDailyDigest`. Resolves the
academy's parents, claims one digest per parent per day (the claim is the
idempotency guard — a second run sends zero), asks a duck-typed
``ParentDigestProvider`` to assemble that family's view, and e-mails it. A family
with no session today yields ``None`` from the provider and is recorded
``skipped_empty`` — no e-mail.

Cross-context data (children, teaching focus, pathway placement, dues, autopay,
portal status) is assembled by the provider at the composition root, so this use
case imports nothing from other bounded contexts (ADR-0005). The rendered body
already picks Variant A vs B from ``view.on_portal``; ``view.reply_to`` (set for
Variant B) is forwarded so the "reply to this email" fallback reaches a real
inbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import ParentDigestView
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    DigestSendRepository,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.models import AcademyAudience


class ParentDigestProvider(Protocol):
    """Assembles one family's digest view for a date (duck-typed).

    Returns ``None`` when the family has no session that day, so the use case
    can skip without e-mailing.
    """

    async def build_view(self, parent_id: str, on_date: date) -> ParentDigestView | None: ...


@dataclass(frozen=True, slots=True)
class SendParentDailyDigestCommand:
    academy_id: str
    digest_date: date


@dataclass(frozen=True, slots=True)
class SendParentDailyDigestResult:
    total_parents: int
    claimed: int
    already_claimed: int
    sent: int
    skipped_empty: int
    failed: int


@dataclass
class SendParentDailyDigest:
    digests: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    provider: ParentDigestProvider

    async def execute(self, command: SendParentDailyDigestCommand) -> SendParentDailyDigestResult:
        digest_date = command.digest_date.isoformat()
        parents = await self.resolver.resolve_academy_audience(AcademyAudience(role="parent"))

        claimed = already_claimed = sent = skipped_empty = failed = 0
        for parent in parents:
            claim = await self.digests.try_claim(command.academy_id, parent.user_id, digest_date)
            if claim is None:
                already_claimed += 1
                continue
            claimed += 1

            try:
                view = await self.provider.build_view(parent.user_id, command.digest_date)
            except Exception as exc:  # view assembly must never crash the run
                await self.digests.mark_failed(claim.digest_id, f"view build failed: {exc}")
                failed += 1
                continue

            if view is None or not view.has_children():
                await self.digests.mark_skipped_empty(claim.digest_id)
                skipped_empty += 1
                continue

            if not parent.email:
                await self.digests.mark_failed(claim.digest_id, "no email address")
                failed += 1
                continue

            subject, body = render_parent_digest(view)
            recipient = ResolvedRecipient(
                user_id=parent.user_id,
                email=parent.email,
                display_name=parent.display_name,
            )
            outcome = await self.sender.send(
                recipient=recipient, subject=subject, body=body, reply_to=view.reply_to
            )
            if outcome.ok:
                await self.digests.mark_sent(claim.digest_id, outcome.provider_message_id)
                sent += 1
            else:
                await self.digests.mark_failed(claim.digest_id, outcome.failed_reason or "unknown")
                failed += 1

        return SendParentDailyDigestResult(
            total_parents=len(parents),
            claimed=claimed,
            already_claimed=already_claimed,
            sent=sent,
            skipped_empty=skipped_empty,
            failed=failed,
        )
