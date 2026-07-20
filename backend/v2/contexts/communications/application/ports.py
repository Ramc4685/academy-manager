"""Communications application ports.

The use case depends on these protocols, not on Mongo/Resend implementations.
Tests inject in-memory fakes; production composition wires Mongo repositories
and a Resend-backed `EmailSendPort`. Per `docs/agent/backend-api-rules.md`,
local/test composition must use a stub send port and never call a real
provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Campaign,
    CoachAudience,
    Delivery,
    DigestSend,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
)


@dataclass(frozen=True, slots=True)
class ResolvedRecipient:
    """A concrete user the campaign will reach."""

    user_id: str
    email: str | None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """Outcome of a single per-recipient send attempt."""

    ok: bool
    provider_message_id: str | None
    failed_reason: str | None


class AudienceResolver(Protocol):
    """Resolves audience descriptors to concrete user lists.

    Implementations must apply tenant scoping (they read from tenant-scoped
    repositories). Returning recipients from another academy is a tenant
    leak.
    """

    async def resolve_academy_audience(
        self, audience: AcademyAudience
    ) -> list[ResolvedRecipient]: ...

    async def resolve_session_audience(
        self, audience: SessionAudience
    ) -> list[ResolvedRecipient]: ...

    async def resolve_coach_audience(self, audience: CoachAudience) -> list[ResolvedRecipient]: ...

    async def resolve_selected_audience(
        self, audience: SelectedRecipientsAudience
    ) -> list[ResolvedRecipient]: ...

    async def resolve_payment_risk_audience(
        self, audience: PaymentRiskAudience
    ) -> list[ResolvedRecipient]: ...


class EmailSendPort(Protocol):
    """Outbound email port.

    The production adapter wraps Resend; the test/local adapter MUST be a stub
    that records sends without contacting a provider.
    """

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> SendOutcome: ...


class CampaignRepository(Protocol):
    async def save(self, campaign: Campaign) -> None: ...
    async def get(self, campaign_id: str) -> Campaign | None: ...


class DeliveryRepository(Protocol):
    async def save_many(self, deliveries: list[Delivery]) -> None: ...
    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]: ...


class DigestSendRepository(Protocol):
    """Persistence + claim-based idempotency for coach daily digests.

    ``try_claim`` inserts a QUEUED row against the unique
    ``(academy_id, coach_id, digest_date)`` index. It returns the new
    ``DigestSend`` on success and ``None`` when a row already exists (the
    duplicate-key error is the idempotency guard — a second scheduler run for
    the same day sends nothing).
    """

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None: ...

    async def record_test_send(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend: ...

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None: ...

    async def mark_failed(self, digest_id: str, reason: str) -> None: ...

    async def mark_skipped_empty(self, digest_id: str) -> None: ...

    async def list_recent(self, academy_id: str, limit: int) -> list[DigestSend]: ...
