"""SendCoachDailyDigest use case.

Resolves the academy's coaches, claims one digest per coach per day (the claim
is the idempotency guard — a second run sends zero), generates that coach's
personalised teaching plan, and e-mails a plain-text digest through the shared
``EmailSendPort``. A coach with nothing to teach is recorded ``skipped_empty``
and receives no e-mail.

*Why not SendCampaign*: campaigns send one shared body to every recipient; this
digest is personalised per coach. Reusing the port + resolver keeps the
Resend/Stub safety gating and recipient resolution without contorting the
campaign model.

The plan is provided through a duck-typed ``PlanProvider`` protocol wired in the
composition root, so communications imports nothing from the coaching context
(ADR-0005).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
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


class PlanProvider(Protocol):
    """Produces a coach's *Today's Teaching Plan* for a date (duck-typed)."""

    async def execute(self, coach_id: str, on_date: date) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class SendCoachDailyDigestCommand:
    academy_id: str
    digest_date: date
    # Per-academy override, sourced from ``notifications.daily_digest_to_admin``
    # (see GetAcademyNotificationsUseCase). Resolved by the caller so this use
    # case stays free of an identity-context import (ADR-0005).
    admin_cc_enabled: bool = False


@dataclass(frozen=True, slots=True)
class SendCoachDailyDigestResult:
    total_coaches: int
    claimed: int
    already_claimed: int
    sent: int
    skipped_empty: int
    failed: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def plan_is_empty(plan: Any) -> bool:
    """A plan with no sessions — or only sessions with no students at all — has
    nothing worth e-mailing."""
    if plan is None:
        return True
    sessions = getattr(plan, "sessions", None) or []
    if not sessions:
        return True
    for session in sessions:
        if (getattr(session, "groups", None) or []) or (getattr(session, "unplaced", None) or []):
            return False
    return True


@dataclass
class SendCoachDailyDigest:
    digests: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    plan_provider: PlanProvider
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    # The academy's subdomain label, so the unsubscribe link lands on the host
    # TenantResolver can actually resolve (#555). Optional: with no lookup the
    # link falls back to the generic frontend host, which the unsubscribe route
    # refuses in SaaS mode rather than accepting on a weakened tenant check.
    academy_slugs: AcademySlugLookup | None = None
    now: Callable[[], datetime] = field(default=_utcnow)

    async def _academy_slug(self, academy_id: str) -> str | None:
        """Resolved once per run, never per recipient. A lookup failure degrades
        the footer to the generic host rather than losing the whole send."""
        if self.academy_slugs is None:
            return None
        try:
            return await self.academy_slugs.slug_for(academy_id)
        except Exception:
            return None

    async def execute(self, command: SendCoachDailyDigestCommand) -> SendCoachDailyDigestResult:
        digest_date = command.digest_date.isoformat()
        academy_slug = await self._academy_slug(command.academy_id)
        coaches = await self.resolver.resolve_academy_audience(AcademyAudience(role="coach"))
        admin_emails: list[str] = []
        if command.admin_cc_enabled:
            admins = await self.resolver.resolve_academy_audience(AcademyAudience(role="admin"))
            admin_emails = sorted({a.email for a in admins if a.email})

        claimed = already_claimed = sent = skipped_empty = failed = 0
        for coach in coaches:
            claim = await self.digests.try_claim(command.academy_id, coach.user_id, digest_date)
            if claim is None:
                already_claimed += 1
                continue
            claimed += 1

            try:
                plan = await self.plan_provider.execute(coach.user_id, command.digest_date)
            except Exception as exc:  # plan generation must never crash the run
                await self.digests.mark_failed(claim.digest_id, f"plan generation failed: {exc}")
                failed += 1
                continue

            if plan_is_empty(plan):
                await self.digests.mark_skipped_empty(claim.digest_id)
                skipped_empty += 1
                continue

            if not coach.email:
                # Not retryable: the address is missing from the coach's user
                # record, so the next tick would regenerate the plan and fail
                # identically. Fixing it is a data task, not a delivery retry.
                await self.digests.mark_failed(claim.digest_id, "no email address", retryable=False)
                failed += 1
                continue

            subject, body = render_coach_digest(
                plan,
                unsubscribe_url=self.unsubscribe_links.build(
                    academy_id=command.academy_id,
                    user_id=coach.user_id,
                    academy_slug=academy_slug,
                ),
            )
            recipient = ResolvedRecipient(
                user_id=coach.user_id,
                email=coach.email,
                display_name=coach.display_name,
            )
            # BCC (not CC) so no coach sees the other admins' addresses.
            bcc = [e for e in admin_emails if e != coach.email]
            outcome = await self.sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                bcc=bcc or None,
                category=EmailCategory.DIGEST,
            )
            if outcome.ok:
                await self.digests.mark_sent(claim.digest_id, outcome.provider_message_id)
                sent += 1
            elif outcome.suppressed:
                # Not retryable — see SendParentDailyDigest: a re-claimed
                # FAILED row would re-hit the same gate every tick.
                await self.digests.mark_failed(
                    claim.digest_id, outcome.failed_reason or "blocked", retryable=False
                )
                failed += 1
            else:
                await self.digests.mark_failed(claim.digest_id, outcome.failed_reason or "unknown")
                failed += 1

        return SendCoachDailyDigestResult(
            total_coaches=len(coaches),
            claimed=claimed,
            already_claimed=already_claimed,
            sent=sent,
            skipped_empty=skipped_empty,
            failed=failed,
        )
