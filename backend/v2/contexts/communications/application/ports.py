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

from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.email_preferences import EmailPreferences
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
    #: The message was refused by a send-time gate (an unsubscribe preference
    #: or a provider suppression), not by the provider. It is a *terminal*
    #: outcome: retrying re-hits the same gate, so callers must record it
    #: non-retryably rather than scheduling another attempt.
    suppressed: bool = False


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

    ``category`` classifies the message for the send-time gates applied by
    ``GatedEmailSendPort``. It defaults to ``TRANSACTIONAL`` on purpose: an
    un-classified call site is the record of an existing commercial
    relationship (invoice, dunning notice, login invite) and must never be
    dropped by an unsubscribe preference.
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
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome: ...


class AcademySlugLookup(Protocol):
    """The academy's subdomain label, for building outbound links (#555).

    ``TenantResolver`` (ADR-0007) reads the tenant from the first label of the
    request host, so every emailed link has to be built on the academy's own
    subdomain rather than the deployment's generic ``frontend_url``. The send
    loops resolve the slug once per run and hand it to
    ``UnsubscribeLinkBuilder.build``.
    """

    async def slug_for(self, academy_id: str) -> str | None: ...


class EmailPreferenceRepository(Protocol):
    """Per-recipient email preferences (#555), tenant-scoped.

    An absent document means *opted in*: rows are written only when someone
    actually changes something, so the store stays a record of choices rather
    than a row per user.
    """

    async def get(self, user_id: str) -> EmailPreferences | None: ...

    async def set_opt_outs(
        self,
        *,
        user_id: str,
        email: str | None,
        campaigns_opted_out: bool,
        digests_opted_out: bool,
        source: str,
    ) -> EmailPreferences:
        """Idempotently record this recipient's choices and return them."""
        ...


class CampaignRepository(Protocol):
    async def save(self, campaign: Campaign) -> None: ...
    async def get(self, campaign_id: str) -> Campaign | None: ...

    async def try_claim(self, campaign: Campaign) -> bool:
        """Insert-first idempotency claim.

        Inserts the campaign against the unique
        ``(academy_id, idempotency_key)`` index. Returns ``True`` when this
        call won the claim (the campaign row now exists) and ``False`` when a
        campaign with the same idempotency key already exists — the duplicate
        key error is the idempotency guard, mirroring the digest
        ``try_claim`` pattern.
        """
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Campaign | None:
        """Look up the campaign that holds the given idempotency claim."""
        ...


class DeliveryRepository(Protocol):
    async def save_many(self, deliveries: list[Delivery]) -> None:
        """Upsert delivery rows keyed by ``delivery_id``.

        Called once with the QUEUED batch before the send loop (so a crashed
        run is visible and countable) and again with final per-recipient
        states after the loop; the second call overwrites the queued rows.
        """
        ...

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]: ...


class DigestSendRepository(Protocol):
    """Persistence + claim-based idempotency for coach daily digests.

    ``try_claim`` inserts a QUEUED row against the unique
    ``(academy_id, coach_id, digest_date)`` index. It returns the new
    ``DigestSend`` on success and ``None`` when a row already exists (the
    duplicate-key error is the idempotency guard — a second scheduler run for
    the same day sends nothing).

    One exception to "a row already exists ⇒ None": a row left in ``FAILED``
    with attempts remaining is *re-claimed* and returned, so the next hourly
    tick retries a send that a transient provider outage lost. The re-claim is
    a single conditional update, so two concurrent ticks cannot both win it,
    and it can never match a ``SENT`` or in-flight ``QUEUED`` row — retrying a
    failure must never turn into sending twice.
    """

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None: ...

    async def record_test_send(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend: ...

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None: ...

    async def mark_failed(self, digest_id: str, reason: str, *, retryable: bool = True) -> None: ...

    async def mark_skipped_empty(self, digest_id: str) -> None: ...

    async def list_recent(self, academy_id: str, limit: int) -> list[DigestSend]: ...
