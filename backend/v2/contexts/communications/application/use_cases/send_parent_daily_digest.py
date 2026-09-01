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

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import ParentDigestView
from backend.v2.contexts.communications.application.ports import (
    AcademySlugLookup,
    AudienceResolver,
    DigestSendRepository,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
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
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    # The academy's subdomain label, so the unsubscribe link lands on the host
    # TenantResolver can actually resolve (#555). Optional: with no lookup the
    # link falls back to the generic frontend host, which the unsubscribe route
    # refuses in SaaS mode rather than accepting on a weakened tenant check.
    academy_slugs: AcademySlugLookup | None = None

    async def _academy_slug(self, academy_id: str) -> str | None:
        """Resolved once per run, never per recipient. A lookup failure degrades
        the footer to the generic host rather than losing the whole send."""
        if self.academy_slugs is None:
            return None
        try:
            return await self.academy_slugs.slug_for(academy_id)
        except Exception:
            return None

    async def execute(self, command: SendParentDailyDigestCommand) -> SendParentDailyDigestResult:
        digest_date = command.digest_date.isoformat()
        academy_slug = await self._academy_slug(command.academy_id)
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
                # Not retryable — see the coach digest: a missing address is a
                # data problem, and retrying only rebuilds the view to fail again.
                await self.digests.mark_failed(claim.digest_id, "no email address", retryable=False)
                failed += 1
                continue

            subject, body = render_parent_digest(
                view,
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=command.academy_id,
                    user_id=parent.user_id,
                    academy_slug=academy_slug,
                ),
            )
            recipient = ResolvedRecipient(
                user_id=parent.user_id,
                email=parent.email,
                display_name=parent.display_name,
            )
            outcome = await self.sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                reply_to=view.reply_to,
                category=EmailCategory.DIGEST,
            )
            if outcome.ok:
                await self.digests.mark_sent(claim.digest_id, outcome.provider_message_id)
                sent += 1
            elif outcome.suppressed:
                # NOT retryable. A FAILED row with attempts left is re-claimed
                # by the next hourly tick, so a retryable unsubscribe would
                # rebuild the plan and re-hit the same gate three times a day
                # forever, churning attempt_count and polluting the ops
                # digest's "lost digests" count. Non-retryable rows are
                # excluded from that count by design — the right bucket.
                await self.digests.mark_failed(
                    claim.digest_id, outcome.failed_reason or "blocked", retryable=False
                )
                failed += 1
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
