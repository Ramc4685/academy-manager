"""SendCampaign use case.

Resolves the audience to a concrete recipient list, claims an idempotency key
(insert-first against a unique index, mirroring the digest ``try_claim``
pattern), persists the campaign as SENDING plus the full QUEUED delivery
batch, sends one delivery per recipient via the injected send port, records
per-recipient state, then advances the campaign to SENT.

Idempotency (#512): a retried POST must not re-email the audience. The claim
key is either supplied by the caller or derived from the campaign content
(academy + sender + subject + body + audience), so an identical retry resolves
to the already-claimed campaign and sends nothing. Persisting the QUEUED batch
before the send loop means a mid-loop crash leaves visible delivery rows
instead of an invisibly half-sent campaign.

No real email leaves the system here — the use case is purely orchestrated
over ports. Composition decides whether the production Resend adapter or the
stub send port is wired.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from backend.v2.contexts.communications.application.ports import (
    AcademyBrandLookup,
    AcademySlugLookup,
    AudienceResolver,
    CampaignRepository,
    DeliveryRepository,
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.send_gate import RecipientGate
from backend.v2.contexts.communications.application.unsubscribe_footer import (
    append_unsubscribe_footer,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    ONE_CLICK_UNSUBSCRIBE_PATH,
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.errors import (
    AudienceChangedError,
    DuplicateCampaignError,
    EmptyAudienceError,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Audience,
    Campaign,
    CampaignStatus,
    CoachAudience,
    Delivery,
    DeliveryStatus,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
    audience_descriptor,
)
from backend.v2.shared.comms.email_theme import EmailBrand
from backend.v2.shared.comms.send_idempotency import send_idempotency_scope
from backend.v2.shared.ids import new_ulid


@dataclass(frozen=True, slots=True)
class SendCampaignCommand:
    academy_id: str
    sender_id: str
    audience: Audience
    subject: str
    body: str
    idempotency_key: str | None = None
    #: The ``audience_fingerprint`` the admin reviewed (#1031). When set and the
    #: audience now resolves differently, the send is refused before any claim.
    expected_audience_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class SendCampaignResult:
    campaign_id: str
    total_recipients: int
    sent_count: int
    failed_count: int
    deduplicated: bool = False
    #: Handed to ``ProcessCampaignQueue``; the counts fill in as it sends.
    queued: bool = False


@dataclass(frozen=True, slots=True)
class CampaignAudiencePreview:
    """Who a campaign would reach, resolved exactly as the send resolves it.

    ``recipient_count`` is unique email addresses; ``family_count`` the primary
    parents among them and ``contact_count`` the opted-in family contacts. An
    enrollment count is never a family count: siblings share a parent (#1029).
    """

    recipient_count: int
    family_count: int
    contact_count: int
    #: #1031: who gets it, who does not and why, and a fingerprint of the
    #: recipient addresses the send can check against.
    recipients: tuple[ResolvedRecipient, ...] = ()
    exclusions: tuple[CampaignExclusion, ...] = ()
    audience_fingerprint: str = ""


#: Why a resolved person gets no copy (#1031). The send applies the same rules.
EXCLUSION_MISSING_EMAIL = "missing_email"
EXCLUSION_DUPLICATE_ADDRESS = "duplicate_address"
EXCLUSION_SUPPRESSED = "suppressed"
EXCLUSION_UNSUBSCRIBED = "unsubscribed"


@dataclass(frozen=True, slots=True)
class CampaignExclusion:
    display_name: str | None
    email: str | None
    reason: str
    is_family_contact: bool = False


def _exclusion_reason(gate_reason: str | None) -> str:
    """Map a gate verdict ("suppressed:hard_bounce", "unsubscribed:campaign")
    to a public reason; the raw provider detail stays out of the preview."""
    if gate_reason and gate_reason.startswith("suppressed"):
        return EXCLUSION_SUPPRESSED
    return EXCLUSION_UNSUBSCRIBED


def audience_fingerprint(recipients: Sequence[ResolvedRecipient]) -> str:
    emails = sorted({(r.email or "").strip().lower() for r in recipients})
    return hashlib.sha256("\n".join(emails).encode("utf-8")).hexdigest()


def derive_idempotency_key(command: SendCampaignCommand) -> str:
    """Content-derived idempotency key for callers that supply none.

    A retried request with identical content (same academy, sender, subject,
    body, and audience) hashes to the same key and is deduplicated.
    """

    material = json.dumps(
        {
            "academy_id": command.academy_id,
            "sender_id": command.sender_id,
            "subject": command.subject,
            "body": command.body,
            "audience": audience_descriptor(command.audience),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "auto-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _dedupe_recipients(recipients: list[ResolvedRecipient]) -> list[ResolvedRecipient]:
    return _partition_duplicates(recipients)[0]


def _partition_duplicates(
    recipients: list[ResolvedRecipient],
) -> tuple[list[ResolvedRecipient], list[ResolvedRecipient]]:
    """Drop duplicate recipients before any email leaves (belt-and-suspenders).

    Resolvers are expected to return each person once, but a residual
    duplicate path exists when the same person is matched through two user
    docs (e.g. one keyed by ``user_id`` and another matched via ``auth_uid``
    with a different ``user_id``). Dedupe by user_id and, when present, by
    normalized email so one person never receives the same campaign twice.
    First occurrence wins, order preserved.
    """

    seen_user_ids: set[str] = set()
    seen_emails: set[str] = set()
    unique: list[ResolvedRecipient] = []
    dropped: list[ResolvedRecipient] = []
    for recipient in recipients:
        email_key = recipient.email.strip().lower() if recipient.email else None
        if recipient.user_id in seen_user_ids or (email_key and email_key in seen_emails):
            dropped.append(recipient)
            continue
        seen_user_ids.add(recipient.user_id)
        if email_key:
            seen_emails.add(email_key)
        unique.append(recipient)
    return unique, dropped


@dataclass
class _CampaignMail:
    """One recipient's copy: footer, one-click header, brand. Shared by the
    inline loop and the background worker so both send the same email."""

    sender: EmailSendPort
    unsubscribe_links: UnsubscribeLinkBuilder
    list_unsubscribe: bool

    async def deliver(
        self,
        *,
        academy_id: str,
        subject: str,
        body: str,
        recipient: ResolvedRecipient,
        academy_slug: str | None,
        brand: EmailBrand | None,
    ) -> SendOutcome:
        postal_address = brand.postal_address if brand and self.list_unsubscribe else None
        footer_url = self.unsubscribe_links.build(
            academy_id=academy_id, user_id=recipient.user_id, academy_slug=academy_slug
        )
        one_click = (
            self.unsubscribe_links.build(
                academy_id=academy_id,
                user_id=recipient.user_id,
                academy_slug=academy_slug,
                path=ONE_CLICK_UNSUBSCRIBE_PATH,
            )
            if self.list_unsubscribe
            else None
        )
        return await self.sender.send(
            recipient=recipient,
            subject=subject,
            body=append_unsubscribe_footer(body, footer_url, postal_address),
            category=EmailCategory.CAMPAIGN,
            reply_to=brand.reply_to if brand else None,
            sender_name=brand.sender_name if brand else None,
            unsubscribe_url=one_click,
        )


async def _lookup_slug(lookup: AcademySlugLookup | None, academy_id: str) -> str | None:
    """Resolved once per run, never per recipient. A lookup failure degrades
    the footer to the generic host rather than losing the whole send."""
    if lookup is None:
        return None
    try:
        return await lookup.slug_for(academy_id)
    except Exception:
        return None


async def _lookup_brand(lookup: AcademyBrandLookup | None, academy_id: str) -> EmailBrand | None:
    if lookup is None:
        return None
    try:
        return await lookup.brand_for(academy_id)
    except Exception:
        return None


@dataclass
class SendCampaign:
    campaigns: CampaignRepository
    deliveries: DeliveryRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    # CAN-SPAM: every campaign body gets a per-recipient opt-out footer. The
    # default builder mints no token (no secret configured), which renders the
    # portal-pointer fallback rather than a dead link — the notice ships either
    # way.
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    # The academy's subdomain label, so the unsubscribe link lands on the host
    # TenantResolver can actually resolve (#555). Optional: with no lookup the
    # link falls back to the generic frontend host, which the unsubscribe route
    # refuses in SaaS mode rather than accepting on a weakened tenant check.
    academy_slugs: AcademySlugLookup | None = None
    # Sender display name / reply-to (L9a). Optional: without it the From
    # header stays the platform address and there is no reply-to.
    brands: AcademyBrandLookup | None = None
    # L11 item 8 (EMAIL_LIST_UNSUBSCRIBE_ENABLED): RFC 8058 one-click
    # List-Unsubscribe headers and the academy's postal address in the footer.
    # Off keeps every campaign byte-for-byte as before.
    list_unsubscribe: bool = False
    # L11 item 7 (CAMPAIGN_BACKGROUND_SEND_ENABLED): persist the queue and
    # return; ``ProcessCampaignQueue`` sends it. Off keeps the inline loop.
    background: bool = False
    #: The send-time gates (suppression, preferences), consulted read-only by
    #: ``preview`` so it explains who the send would refuse (#1031). The send
    #: itself still goes through the gated sender.
    gates: Sequence[RecipientGate] = ()
    now: Callable[[], datetime] = field(default=_utcnow)
    new_id: Callable[[], str] = field(default=new_ulid)

    async def execute(self, command: SendCampaignCommand) -> SendCampaignResult:
        if command.expected_audience_fingerprint is not None:
            current = await self.preview(command.audience)
            if current.audience_fingerprint != command.expected_audience_fingerprint:
                raise AudienceChangedError(
                    "the audience changed since it was reviewed; review it again"
                )

        recipients = _dedupe_recipients(await self._resolve(command.audience))
        if not recipients:
            raise EmptyAudienceError(
                "audience resolved to zero recipients; refusing to record a send"
            )

        idempotency_key = command.idempotency_key or derive_idempotency_key(command)

        created_at = self.now()
        campaign = Campaign.new(
            campaign_id=self.new_id(),
            academy_id=command.academy_id,
            sender_id=command.sender_id,
            audience=command.audience,
            subject=command.subject,
            body=command.body,
            created_at=created_at,
            idempotency_key=idempotency_key,
            # Claimed inline: the worker must not see this campaign until every
            # delivery row exists, or it would close it half-queued.
            background=False,
        ).mark_sending()

        claimed = await self.campaigns.try_claim(campaign)
        if not claimed:
            # A campaign already holds this idempotency key: a retried POST or
            # a concurrent duplicate. Report the existing send; email nothing.
            existing = await self.campaigns.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise DuplicateCampaignError(
                    "campaign idempotency claim already held but the claiming "
                    f"campaign could not be read back (key={idempotency_key})"
                )
            rows = await self.deliveries.list_for_campaign(existing.campaign_id)
            return SendCampaignResult(
                campaign_id=existing.campaign_id,
                total_recipients=len(rows),
                sent_count=sum(1 for r in rows if r.status == DeliveryStatus.SENT),
                failed_count=sum(1 for r in rows if r.status == DeliveryStatus.FAILED),
                deduplicated=True,
                # A retry while the queue drains reports "queued", not "0 of N delivered".
                queued=existing.status == CampaignStatus.SENDING,
            )

        # Persist the QUEUED batch before any email leaves, so a mid-loop
        # crash leaves a visible, countable roster instead of a SENDING
        # campaign with zero delivery rows.
        queued: list[Delivery] = [
            Delivery.queued(
                delivery_id=self.new_id(),
                academy_id=command.academy_id,
                campaign_id=campaign.campaign_id,
                recipient=recipient,
            )
            for recipient in recipients
        ]
        await self.deliveries.save_many(queued)

        if self.background:
            # Only now, with the whole queue persisted, hand it to the worker.
            # A crash before this line leaves an inline SENDING campaign that
            # sent nothing and that no worker resumes; the ops digest flags it
            # ("Email campaigns stuck sending").
            await self.campaigns.save(replace(campaign, background=True))
            return SendCampaignResult(
                campaign_id=campaign.campaign_id,
                total_recipients=len(recipients),
                sent_count=0,
                failed_count=0,
                queued=True,
            )

        academy_slug = await _lookup_slug(self.academy_slugs, command.academy_id)
        brand = await _lookup_brand(self.brands, command.academy_id)
        mail = _CampaignMail(self.sender, self.unsubscribe_links, self.list_unsubscribe)
        deliveries: list[Delivery] = []
        sent_count = 0
        failed_count = 0
        for base, recipient in zip(queued, recipients, strict=True):
            outcome = await mail.deliver(
                academy_id=command.academy_id,
                subject=command.subject,
                body=command.body,
                recipient=recipient,
                academy_slug=academy_slug,
                brand=brand,
            )
            if outcome.ok:
                deliveries.append(
                    base.mark_sent(
                        provider_message_id=outcome.provider_message_id,
                        sent_at=self.now(),
                    )
                )
                sent_count += 1
            else:
                # A recipient the send-time gate refused (unsubscribed, or
                # suppressed) is recorded with its reason rather than dropped
                # silently: the admin's delivery log must explain why someone
                # in the audience got nothing. It needs no new DeliveryStatus —
                # nothing was delivered, and the reason carries the detail.
                deliveries.append(base.mark_failed(reason=outcome.failed_reason or "unknown"))
                failed_count += 1
        await self.deliveries.save_many(deliveries)

        await self.campaigns.save(campaign.mark_sent(sent_at=created_at))

        return SendCampaignResult(
            campaign_id=campaign.campaign_id,
            total_recipients=len(recipients),
            sent_count=sent_count,
            failed_count=failed_count,
        )

    async def preview(self, audience: Audience) -> CampaignAudiencePreview:
        """Resolve the audience without sending or recording anything."""
        unique, dropped = _partition_duplicates(await self._resolve(audience))
        exclusions = [
            CampaignExclusion(
                r.display_name, r.email, EXCLUSION_DUPLICATE_ADDRESS, r.is_family_contact
            )
            for r in dropped
            if r.email and r.email.strip()
        ]
        reachable: list[ResolvedRecipient] = []
        for r in unique:
            if not (r.email and r.email.strip()):
                exclusions.append(
                    CampaignExclusion(
                        r.display_name, None, EXCLUSION_MISSING_EMAIL, r.is_family_contact
                    )
                )
                continue
            refusal = await self._gate_refusal(r)
            if refusal is not None:
                exclusions.append(
                    CampaignExclusion(r.display_name, r.email, refusal, r.is_family_contact)
                )
                continue
            reachable.append(r)
        contacts = sum(1 for r in reachable if r.is_family_contact)
        return CampaignAudiencePreview(
            recipient_count=len(reachable),
            family_count=len(reachable) - contacts,
            contact_count=contacts,
            recipients=tuple(reachable),
            exclusions=tuple(exclusions),
            audience_fingerprint=audience_fingerprint(reachable),
        )

    async def _gate_refusal(self, recipient: ResolvedRecipient) -> str | None:
        for gate in self.gates:
            verdict = await gate.check(
                recipient_user_id=recipient.user_id,
                email=recipient.email or "",
                category=EmailCategory.CAMPAIGN,
            )
            if not verdict.allowed:
                return _exclusion_reason(verdict.reason)
        return None

    async def _resolve(self, audience: Audience) -> list[ResolvedRecipient]:
        if isinstance(audience, AcademyAudience):
            return await self.resolver.resolve_academy_audience(audience)
        if isinstance(audience, SessionAudience):
            return await self.resolver.resolve_session_audience(audience)
        if isinstance(audience, CoachAudience):
            return await self.resolver.resolve_coach_audience(audience)
        if isinstance(audience, SelectedRecipientsAudience):
            return await self.resolver.resolve_selected_audience(audience)
        if isinstance(audience, PaymentRiskAudience):
            return await self.resolver.resolve_payment_risk_audience(audience)
        raise TypeError(f"Unhandled audience type: {audience!r}")


#: A claim this old belongs to a worker that died mid-send. The retry reuses the
#: delivery's idempotency scope, so the provider drops a copy that did go out
#: (Resend keeps keys 24 hours, far longer than this).
CLAIM_STALE_AFTER = timedelta(minutes=10)
#: A delivery whose send keeps killing its worker is given up after this many
#: claims, so the campaign can close.
MAX_CLAIM_ATTEMPTS = 5


@dataclass
class ProcessCampaignQueue:
    """Sends background campaigns for the current academy (L11 item 7).

    Resumable and never double-sends to a person: each delivery is claimed
    atomically before its send, its final state is written right after, and
    the send runs in the idempotency scope ``campaign:<delivery_id>``. A crash
    leaves at most one claimed row per worker, retried once the claim is stale
    under the same provider key. The campaign is marked SENT when no QUEUED row
    remains.
    """

    campaigns: CampaignRepository
    deliveries: DeliveryRepository
    sender: EmailSendPort
    unsubscribe_links: UnsubscribeLinkBuilder = field(default_factory=UnsubscribeLinkBuilder)
    academy_slugs: AcademySlugLookup | None = None
    brands: AcademyBrandLookup | None = None
    list_unsubscribe: bool = False
    now: Callable[[], datetime] = field(default=_utcnow)

    async def execute(self) -> int:
        """Returns the number of deliveries attempted this tick."""
        attempted = 0
        mail = _CampaignMail(self.sender, self.unsubscribe_links, self.list_unsubscribe)
        for campaign in await self.campaigns.list_background_sending():
            slug = await _lookup_slug(self.academy_slugs, campaign.academy_id)
            brand = await _lookup_brand(self.brands, campaign.academy_id)
            while True:
                now = self.now()
                token = new_ulid()
                row = await self.deliveries.claim_next_queued(
                    campaign.campaign_id,
                    now=now,
                    stale_before=now - CLAIM_STALE_AFTER,
                    token=token,
                    max_attempts=MAX_CLAIM_ATTEMPTS,
                )
                if row is None:
                    break
                attempted += 1
                with send_idempotency_scope(f"campaign:{row.delivery_id}"):
                    outcome = await mail.deliver(
                        academy_id=campaign.academy_id,
                        subject=campaign.subject,
                        body=campaign.body,
                        recipient=ResolvedRecipient(
                            user_id=row.recipient_user_id, email=row.recipient_email
                        ),
                        academy_slug=slug,
                        brand=brand,
                    )
                done = (
                    row.mark_sent(
                        provider_message_id=outcome.provider_message_id, sent_at=self.now()
                    )
                    if outcome.ok
                    else row.mark_failed(reason=outcome.failed_reason or "unknown")
                )
                # Conditional on our claim token: a worker whose claim went stale
                # and was taken over must not overwrite the newer result.
                await self.deliveries.finish_claimed(done, token=token)
            now = self.now()
            await self.deliveries.fail_exhausted(
                campaign.campaign_id,
                max_attempts=MAX_CLAIM_ATTEMPTS,
                stale_before=now - CLAIM_STALE_AFTER,
            )
            rows = await self.deliveries.list_for_campaign(campaign.campaign_id)
            if not any(r.status == DeliveryStatus.QUEUED for r in rows):
                await self.campaigns.save(campaign.mark_sent(sent_at=self.now()))
        return attempted
