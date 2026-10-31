"""SendParentReportCards use case.

On the first academy-local day of a month, e-mail every family one report
card covering each child's month just ended: new skills, classes attended,
current level and a focus for the new month. Any other day sends nothing. The
claim ``(academy_id, parent_id, report month)`` is the idempotency guard: a
second run in the same month sends zero.

Which families get a card, and what is on it, is assembled by a duck-typed
``ReportCardProvider`` at the composition root, so this use case imports
nothing from other bounded contexts (ADR-0005).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.v2.contexts.communications.application.parent_report_card import (
    FamilyReportCard,
    render_parent_report_card,
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


class ReportCardProvider(Protocol):
    """Families with a child active in ``[start, end)``, one entry per parent.

    ``month_name`` / ``next_month_name`` are filled in by the provider from
    ``start`` and ``end``."""

    async def families_for_month(
        self, start: datetime, end: datetime
    ) -> list[FamilyReportCard]: ...


@dataclass(frozen=True, slots=True)
class SendParentReportCardsCommand:
    academy_id: str
    #: Academy-local "now" (tz-aware). Sends only when this is the 1st.
    local_now: datetime


@dataclass(frozen=True, slots=True)
class SendParentReportCardsResult:
    families: int
    already_claimed: int
    sent: int
    failed: int
    #: Of ``failed``, the provider errors a later tick can retry.
    retryable_failed: int = 0


def report_month(local_now: datetime) -> tuple[datetime, datetime]:
    """``[start, end)`` of the calendar month before ``local_now``, local midnights."""
    end = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year, month = (end.year - 1, 12) if end.month == 1 else (end.year, end.month - 1)
    # Same tzinfo, so a DST change inside the month keeps local midnight.
    return end.replace(year=year, month=month), end


def month_names(start: datetime) -> tuple[str, str]:
    return calendar.month_name[start.month], calendar.month_name[start.month % 12 + 1]


@dataclass
class SendParentReportCards:
    claims: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    provider: ReportCardProvider
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    academy_slugs: AcademySlugLookup | None = None
    brands: AcademyBrandLookup | None = None

    async def execute(self, command: SendParentReportCardsCommand) -> SendParentReportCardsResult:
        if command.local_now.day != 1:
            return SendParentReportCardsResult(0, 0, 0, 0)
        academy_id = command.academy_id
        start, end = report_month(command.local_now)
        families = await self.provider.families_for_month(start, end)
        if not families:
            return SendParentReportCardsResult(0, 0, 0, 0)

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

        month_key = start.strftime("%Y-%m")
        already_claimed = sent = failed = retryable_failed = 0
        for family in families:
            claim = await self.claims.try_claim(academy_id, family.parent_id, month_key)
            if claim is None:
                already_claimed += 1
                continue

            resolved = await self.resolver.resolve_user_ids([family.parent_id])
            recipient = resolved[0] if resolved else None
            if recipient is None or not recipient.email:
                await self.claims.mark_failed(
                    academy_id, claim.digest_id, "no email address", retryable=False
                )
                failed += 1
                continue

            subject, body = render_parent_report_card(
                family,
                brand=brand,
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=academy_id, user_id=recipient.user_id, academy_slug=slug
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

        return SendParentReportCardsResult(
            families=len(families),
            already_claimed=already_claimed,
            sent=sent,
            failed=failed,
            retryable_failed=retryable_failed,
        )
