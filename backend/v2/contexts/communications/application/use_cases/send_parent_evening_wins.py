"""SendParentEveningWins use case.

Once each academy-local evening, e-mail every family whose child mastered a
skill or finished a level today. A day with no win sends nothing. The claim
``(academy_id, parent_id, local date)`` is the idempotency guard, exactly as
for the parent daily digest: a second run the same day sends zero.

Which families had a win, and what the wins were, is assembled by a
duck-typed ``ParentWinsProvider`` at the composition root, so this use case
imports nothing from other bounded contexts (ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.v2.contexts.communications.application.parent_wins import (
    FamilyWins,
    render_parent_wins,
)
from backend.v2.contexts.communications.application.ports import (
    AcademyBrandLookup,
    AcademySlugLookup,
    AudienceResolver,
    DigestSendRepository,
    EmailSendPort,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience


class ParentWinsProvider(Protocol):
    """Families with at least one win in ``[start, end)``, one entry per parent."""

    async def families_with_wins(self, start: datetime, end: datetime) -> list[FamilyWins]: ...


@dataclass(frozen=True, slots=True)
class SendParentEveningWinsCommand:
    academy_id: str
    #: Academy-local "now" (tz-aware). Today's wins are local midnight to now.
    local_now: datetime


@dataclass(frozen=True, slots=True)
class SendParentEveningWinsResult:
    families: int
    already_claimed: int
    sent: int
    failed: int
    #: Failures a later attempt may fix (a provider error). The scheduler
    #: retries the day when this is non-zero; sent families stay claimed.
    retryable_failed: int = 0


@dataclass
class SendParentEveningWins:
    claims: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    provider: ParentWinsProvider
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    academy_slugs: AcademySlugLookup | None = None
    brands: AcademyBrandLookup | None = None

    async def execute(self, command: SendParentEveningWinsCommand) -> SendParentEveningWinsResult:
        academy_id = command.academy_id
        start = command.local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        families = await self.provider.families_with_wins(start, command.local_now)
        if not families:
            return SendParentEveningWinsResult(0, 0, 0, 0)

        # Same degradation as the parent digest: a lookup failure costs the
        # branding or the subdomain link, never the send.
        try:
            slug = await self.academy_slugs.slug_for(academy_id) if self.academy_slugs else None
        except Exception:
            slug = None
        try:
            brand = await self.brands.brand_for(academy_id) if self.brands else None
        except Exception:
            brand = None

        win_date = command.local_now.date().isoformat()
        already_claimed = sent = failed = retryable_failed = 0
        for family in families:
            claim = await self.claims.try_claim(academy_id, family.parent_id, win_date)
            if claim is None:
                already_claimed += 1
                continue

            resolved = await self.resolver.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=(family.parent_id,))
            )
            recipient = resolved[0] if resolved else None
            if recipient is None or not recipient.email:
                await self.claims.mark_failed(
                    academy_id, claim.digest_id, "no email address", retryable=False
                )
                failed += 1
                continue

            subject, body = render_parent_wins(
                family,
                brand=brand,
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=academy_id, user_id=family.parent_id, academy_slug=slug
                ),
            )
            outcome = await self.sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                reply_to=brand.reply_to if brand else None,
                category=EmailCategory.DIGEST,
                sender_name=brand.sender_name if brand else None,
            )
            if outcome.ok:
                await self.claims.mark_sent(
                    academy_id, claim.digest_id, outcome.provider_message_id
                )
                sent += 1
            else:
                # An unsubscribe or suppression is terminal (see the parent
                # digest); a provider error stays retryable.
                await self.claims.mark_failed(
                    academy_id,
                    claim.digest_id,
                    outcome.failed_reason or "unknown",
                    retryable=not outcome.suppressed,
                )
                failed += 1
                retryable_failed += not outcome.suppressed

        return SendParentEveningWinsResult(
            families=len(families),
            already_claimed=already_claimed,
            sent=sent,
            failed=failed,
            retryable_failed=retryable_failed,
        )
