"""SendCampaign use case.

Resolves the audience to a concrete recipient list, persists the campaign as
SENDING, sends one delivery per recipient via the injected send port, records
per-recipient state, then advances the campaign to SENT.

No real email leaves the system here — the use case is purely orchestrated
over ports. Composition decides whether the production Resend adapter or the
stub send port is wired.
"""

from __future__ import annotations

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
from backend.v2.contexts.communications.domain.errors import EmptyAudienceError
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Audience,
    Campaign,
    CoachAudience,
    Delivery,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
)
from backend.v2.shared.ids import new_ulid


@dataclass(frozen=True, slots=True)
class SendCampaignCommand:
    academy_id: str
    sender_id: str
    audience: Audience
    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class SendCampaignResult:
    campaign_id: str
    total_recipients: int
    sent_count: int
    failed_count: int


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

        created_at = self.now()
        campaign = Campaign.new(
            campaign_id=self.new_id(),
            academy_id=command.academy_id,
            sender_id=command.sender_id,
            audience=command.audience,
            subject=command.subject,
            body=command.body,
            created_at=created_at,
        ).mark_sending()
        await self.campaigns.save(campaign)

        deliveries: list[Delivery] = []
        sent_count = 0
        failed_count = 0
        for recipient in recipients:
            base = Delivery.queued(
                delivery_id=self.new_id(),
                academy_id=command.academy_id,
                campaign_id=campaign.campaign_id,
                recipient=recipient,
            )
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
