"""Communications domain models — campaigns, deliveries, audiences.

Audience is a typed discriminated union, not a free-form dict, so admins can
target real groups without smuggling raw Mongo filters across the boundary.

Persistence shape (target collections; migrations 0090/0091):

    message_campaigns
      campaign_id, academy_id, sender_id, channel, audience_type,
      audience_filter, subject, body, status, created_at, sent_at

    message_deliveries
      delivery_id, academy_id, campaign_id, recipient_user_id,
      recipient_email, status, provider_message_id, sent_at, opened_at,
      failed_reason
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from backend.v2.contexts.communications.domain.errors import InvalidAudienceError

# ---------------------------------------------------------------------------
# Audience discriminated union
# ---------------------------------------------------------------------------


AudienceRole = Literal["parent", "coach", "admin"]


@dataclass(frozen=True, slots=True)
class AcademyAudience:
    """Everyone in the academy with the given app role."""

    role: AudienceRole = "parent"

    type: Literal["academy"] = field(default="academy", init=False)


@dataclass(frozen=True, slots=True)
class SessionAudience:
    """Parents enrolled in a specific session."""

    session_id: str

    type: Literal["session"] = field(default="session", init=False)


@dataclass(frozen=True, slots=True)
class CoachAudience:
    """Coaches, optionally narrowed to one session's coach roster."""

    session_id: str | None = None

    type: Literal["coach"] = field(default="coach", init=False)


@dataclass(frozen=True, slots=True)
class SelectedRecipientsAudience:
    """An explicit list of users (resolved via admin search UI)."""

    user_ids: tuple[str, ...]

    type: Literal["selected"] = field(default="selected", init=False)

    def __post_init__(self) -> None:
        if not self.user_ids:
            raise InvalidAudienceError("selected audience requires at least one user_id")


@dataclass(frozen=True, slots=True)
class PaymentRiskAudience:
    """Families with overdue balances."""

    min_days_overdue: int = 1

    type: Literal["payment_risk"] = field(default="payment_risk", init=False)


Audience = (
    AcademyAudience
    | SessionAudience
    | CoachAudience
    | SelectedRecipientsAudience
    | PaymentRiskAudience
)


def parse_audience(raw: Mapping[str, Any]) -> Audience:
    """Build an Audience from an untyped dict (e.g., decoded request body)."""

    if not isinstance(raw, Mapping) or "type" not in raw:
        raise InvalidAudienceError("audience descriptor must include 'type'")

    audience_type = raw["type"]
    if audience_type == "academy":
        role = raw.get("role", "parent")
        if role not in ("parent", "coach", "admin"):
            raise InvalidAudienceError(f"unknown academy role: {role!r}")
        return AcademyAudience(role=role)
    if audience_type == "session":
        session_id = raw.get("session_id")
        if not session_id:
            raise InvalidAudienceError("session audience requires session_id")
        return SessionAudience(session_id=str(session_id))
    if audience_type == "coach":
        session_id = raw.get("session_id")
        return CoachAudience(session_id=str(session_id) if session_id else None)
    if audience_type == "selected":
        user_ids = raw.get("user_ids") or []
        if not isinstance(user_ids, list | tuple) or not user_ids:
            raise InvalidAudienceError("selected audience requires non-empty user_ids list")
        return SelectedRecipientsAudience(user_ids=tuple(str(u) for u in user_ids))
    if audience_type == "payment_risk":
        min_days = int(raw.get("min_days_overdue", 1))
        if min_days < 0:
            raise InvalidAudienceError("min_days_overdue must be >= 0")
        return PaymentRiskAudience(min_days_overdue=min_days)
    raise InvalidAudienceError(f"unknown audience type: {audience_type!r}")


def audience_descriptor(audience: Audience) -> dict[str, Any]:
    """Return the persistence-friendly dict for an audience."""

    if isinstance(audience, AcademyAudience):
        return {"type": "academy", "role": audience.role}
    if isinstance(audience, SessionAudience):
        return {"type": "session", "session_id": audience.session_id}
    if isinstance(audience, CoachAudience):
        return {"type": "coach", "session_id": audience.session_id}
    if isinstance(audience, SelectedRecipientsAudience):
        return {"type": "selected", "user_ids": list(audience.user_ids)}
    if isinstance(audience, PaymentRiskAudience):
        return {"type": "payment_risk", "min_days_overdue": audience.min_days_overdue}
    raise InvalidAudienceError(f"unhandled audience: {audience!r}")


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


Channel = Literal["email"]


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    academy_id: str
    sender_id: str
    channel: Channel
    audience: Audience
    subject: str
    body: str
    status: CampaignStatus
    created_at: datetime
    sent_at: datetime | None

    @classmethod
    def new(
        cls,
        *,
        campaign_id: str,
        academy_id: str,
        sender_id: str,
        audience: Audience,
        subject: str,
        body: str,
        created_at: datetime,
        channel: Channel = "email",
    ) -> Campaign:
        return cls(
            campaign_id=campaign_id,
            academy_id=academy_id,
            sender_id=sender_id,
            channel=channel,
            audience=audience,
            subject=subject,
            body=body,
            status=CampaignStatus.DRAFT,
            created_at=created_at,
            sent_at=None,
        )

    def mark_sending(self) -> Campaign:
        return replace(self, status=CampaignStatus.SENDING)

    def mark_sent(self, *, sent_at: datetime) -> Campaign:
        return replace(self, status=CampaignStatus.SENT, sent_at=sent_at)

    def mark_failed(self) -> Campaign:
        return replace(self, status=CampaignStatus.FAILED)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    OPENED = "opened"


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    academy_id: str
    campaign_id: str
    recipient_user_id: str
    recipient_email: str | None
    status: DeliveryStatus
    provider_message_id: str | None
    sent_at: datetime | None
    opened_at: datetime | None
    failed_reason: str | None

    @classmethod
    def queued(
        cls,
        *,
        delivery_id: str,
        academy_id: str,
        campaign_id: str,
        recipient: ResolvedRecipientLike,
    ) -> Delivery:
        return cls(
            delivery_id=delivery_id,
            academy_id=academy_id,
            campaign_id=campaign_id,
            recipient_user_id=recipient.user_id,
            recipient_email=recipient.email,
            status=DeliveryStatus.QUEUED,
            provider_message_id=None,
            sent_at=None,
            opened_at=None,
            failed_reason=None,
        )

    def mark_sent(self, *, provider_message_id: str | None, sent_at: datetime) -> Delivery:
        return replace(
            self,
            status=DeliveryStatus.SENT,
            provider_message_id=provider_message_id,
            sent_at=sent_at,
            failed_reason=None,
        )

    def mark_failed(self, *, reason: str) -> Delivery:
        return replace(
            self,
            status=DeliveryStatus.FAILED,
            failed_reason=reason,
            provider_message_id=None,
        )


# Structural type hint for cls-method to avoid circular import with ports.
class ResolvedRecipientLike:  # pragma: no cover - structural protocol marker
    user_id: str
    email: str | None


# ---------------------------------------------------------------------------
# DigestSend — coach daily teaching-plan digest (claim-based idempotency)
# ---------------------------------------------------------------------------


class DigestSendStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED_EMPTY = "skipped_empty"


#: How many times a single (academy, recipient, date) digest may be attempted.
#: The first attempt is the ``try_claim`` insert; a FAILED row may be re-claimed
#: until its ``attempt_count`` reaches this ceiling, after which the day's
#: digest stays failed and is surfaced by the ops digest instead of retrying
#: forever on the hourly tick.
MAX_DIGEST_SEND_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DigestSend:
    """One coach's daily digest send for a given date.

    The ``(academy_id, coach_id, digest_date)`` triple is unique — a successful
    ``try_claim`` insert is the idempotency guard, so a coach is e-mailed at
    most once per day even if the scheduler fires twice.

    ``attempt_count`` is what makes a *failure* recoverable without weakening
    that guard: only a row in ``FAILED`` may be re-claimed (never ``SENT``,
    never ``QUEUED``), so a transient Resend outage costs a retry rather than
    the whole day's digest, and a send that already left the building is never
    repeated.
    """

    digest_id: str
    academy_id: str
    coach_id: str
    coach_email: str | None
    digest_date: str  # ISO date (YYYY-MM-DD)
    status: DigestSendStatus
    provider_message_id: str | None
    sent_at: str | None
    failed_reason: str | None
    created_at: datetime
    # "daily" for the scheduled run, "test" for an admin-triggered test send.
    # Test sends bypass the unique (academy, coach, date) idempotency claim.
    kind: str = "daily"
    # 1 on the claiming insert; incremented by each re-claim of a FAILED row.
    attempt_count: int = 1
    # False for a failure no retry can fix — a recipient with no e-mail address.
    # Such a row is never re-claimed (retrying is pure waste: three more plan
    # generations for a message that cannot be addressed) and is not counted as
    # a lost digest by the ops digest, or one un-onboarded coach would pin
    # "attention needed" on every daily report forever. It still appears in the
    # admin delivery log with its reason, which is where that problem belongs.
    retryable: bool = True

    @property
    def attempts_exhausted(self) -> bool:
        """True when no further retry of this day's digest will be attempted."""
        return self.attempt_count >= MAX_DIGEST_SEND_ATTEMPTS

    @classmethod
    def queued(
        cls,
        *,
        digest_id: str,
        academy_id: str,
        coach_id: str,
        coach_email: str | None,
        digest_date: str,
        created_at: datetime,
        kind: str = "daily",
        attempt_count: int = 1,
    ) -> DigestSend:
        return cls(
            digest_id=digest_id,
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=coach_email,
            digest_date=digest_date,
            status=DigestSendStatus.QUEUED,
            provider_message_id=None,
            sent_at=None,
            failed_reason=None,
            created_at=created_at,
            kind=kind,
            attempt_count=attempt_count,
        )

    def mark_sent(self, *, provider_message_id: str | None, sent_at: str) -> DigestSend:
        return replace(
            self,
            status=DigestSendStatus.SENT,
            provider_message_id=provider_message_id,
            sent_at=sent_at,
            failed_reason=None,
        )

    def mark_failed(self, *, reason: str, retryable: bool = True) -> DigestSend:
        return replace(
            self,
            retryable=retryable,
            status=DigestSendStatus.FAILED,
            failed_reason=reason,
            provider_message_id=None,
        )

    def mark_skipped_empty(self) -> DigestSend:
        return replace(self, status=DigestSendStatus.SKIPPED_EMPTY)
