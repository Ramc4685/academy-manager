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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    CampaignRepository,
    DeliveryRepository,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.errors import (
    DuplicateCampaignError,
    EmptyAudienceError,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Audience,
    Campaign,
    CoachAudience,
    Delivery,
    DeliveryStatus,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
    audience_descriptor,
)
from backend.v2.shared.ids import new_ulid


@dataclass(frozen=True, slots=True)
class SendCampaignCommand:
    academy_id: str
    sender_id: str
    audience: Audience
    subject: str
    body: str
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class SendCampaignResult:
    campaign_id: str
    total_recipients: int
    sent_count: int
    failed_count: int
    deduplicated: bool = False


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


@dataclass
class SendCampaign:
    campaigns: CampaignRepository
    deliveries: DeliveryRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    now: Callable[[], datetime] = field(default=_utcnow)
    new_id: Callable[[], str] = field(default=new_ulid)

    async def execute(self, command: SendCampaignCommand) -> SendCampaignResult:
        recipients = await self._resolve(command.audience)
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

        deliveries: list[Delivery] = []
        sent_count = 0
        failed_count = 0
        for base, recipient in zip(queued, recipients, strict=True):
            outcome = await self.sender.send(
                recipient=recipient,
                subject=command.subject,
                body=command.body,
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
