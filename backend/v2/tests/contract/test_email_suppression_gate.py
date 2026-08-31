"""Send-time suppression, end to end over the real Mongo-backed gate (#556).

These tests exercise the seam the way production wires it —
``GatedEmailSendPort(inner=StubEmailSendPort(), suppressions=MongoSuppressionGate(...))``
— so "every send path checks the list" is asserted against the actual send
loops (``SendCampaign``, ``SendCoachDailyDigest``) rather than against the gate
in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaign,
    SendCampaignCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.email_suppression import SuppressionReason
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Campaign,
    CoachAudience,
    Delivery,
    DeliveryStatus,
    DigestSend,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
)
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_suppression_repo import (
    MongoSuppressionGate,
    MongoSuppressionRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort

BOUNCED = "dead@example.com"


async def _gated(
    db: Any,
) -> tuple[GatedEmailSendPort, StubEmailSendPort, MongoSuppressionRepository]:
    await db["email_suppressions"].create_index("email", unique=True)
    repo = MongoSuppressionRepository(db)
    stub = StubEmailSendPort()
    return GatedEmailSendPort(inner=stub, suppressions=MongoSuppressionGate(repo)), stub, repo


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category",
    [EmailCategory.TRANSACTIONAL, EmailCategory.DIGEST, EmailCategory.CAMPAIGN],
)
async def test_hard_bounced_address_is_not_sent_any_category(db, category) -> None:
    """A hard bounce stops transactional mail too.

    The mailbox does not exist, so "delivering the invoice" is not what the
    send would do — it would burn the shared sender domain's reputation for
    every tenant. The invoice is still in the parent portal.
    """
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)

    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email=BOUNCED),
        subject="s",
        body="b",
        category=category,
    )

    assert outcome.ok is False
    assert outcome.suppressed is True
    assert outcome.failed_reason == "suppressed:hard_bounce"
    assert stub.sent == []


@pytest.mark.asyncio
async def test_complaint_blocks_marketing_but_not_transactional(db) -> None:
    """A spam report is a marketing signal, not proof the address is dead."""
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.COMPLAINT)
    recipient = ResolvedRecipient(user_id="u1", email=BOUNCED)

    for blocked in (EmailCategory.DIGEST, EmailCategory.CAMPAIGN):
        outcome = await gated.send(recipient=recipient, subject="s", body="b", category=blocked)
        assert outcome.suppressed is True, blocked
        assert outcome.failed_reason == "suppressed:complaint"

    allowed = await gated.send(
        recipient=recipient, subject="Invoice", body="b", category=EmailCategory.TRANSACTIONAL
    )
    assert allowed.ok is True
    assert [row["subject"] for row in stub.sent] == ["Invoice"]


@pytest.mark.asyncio
async def test_soft_bounce_does_not_suppress(db) -> None:
    """Nothing recorded a suppression for a transient bounce, so mail flows."""
    gated, stub, _ = await _gated(db)
    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email="full@example.com"),
        subject="s",
        body="b",
        category=EmailCategory.DIGEST,
    )
    assert outcome.ok is True
    assert outcome.suppressed is False
    assert len(stub.sent) == 1


@pytest.mark.asyncio
async def test_suppression_is_cross_tenant(db, acad, other_acad) -> None:
    """One shared sender domain ⇒ one shared suppression list.

    The bounce is recorded while ``other_acad`` is the active tenant; the send
    happens under a different one and must still be blocked.
    """
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)

    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email=BOUNCED),
        subject="s",
        body="b",
        category=EmailCategory.CAMPAIGN,
    )
    assert outcome.suppressed is True
    assert stub.sent == []


@pytest.mark.asyncio
async def test_released_address_can_be_mailed_again(db) -> None:
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)
    assert await repo.release(email=BOUNCED, released_by="admin-1") is True

    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email=BOUNCED), subject="s", body="b"
    )
    assert outcome.ok is True
    assert len(stub.sent) == 1


@pytest.mark.asyncio
async def test_reason_escalates_but_never_downgrades(db) -> None:
    _, _, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.COMPLAINT)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)
    assert (await repo.get_active(BOUNCED)).reason is SuppressionReason.HARD_BOUNCE
    await repo.record(email=BOUNCED, reason=SuppressionReason.COMPLAINT)
    assert (await repo.get_active(BOUNCED)).reason is SuppressionReason.HARD_BOUNCE


@pytest.mark.asyncio
async def test_gate_failure_allows_the_send(db) -> None:
    """A store outage must not silently stop all mail (the #435 lesson)."""

    class Exploding:
        async def get_active(self, email: str) -> Any:
            raise RuntimeError("mongo is down")

    gated = GatedEmailSendPort(
        inner=(stub := StubEmailSendPort()),
        suppressions=MongoSuppressionGate(Exploding()),  # type: ignore[arg-type]
    )
    outcome = await gated.send(
        recipient=ResolvedRecipient(user_id="u1", email=BOUNCED), subject="s", body="b"
    )
    assert outcome.ok is True
    assert len(stub.sent) == 1


# ---------------------------------------------------------------------------
# Real send paths: campaign + digest
# ---------------------------------------------------------------------------


@dataclass
class _Resolver:
    recipients: list[ResolvedRecipient] = field(default_factory=list)

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_session_audience(self, audience: SessionAudience) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_coach_audience(self, audience: CoachAudience) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_selected_audience(
        self, audience: SelectedRecipientsAudience
    ) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_payment_risk_audience(
        self, audience: PaymentRiskAudience
    ) -> list[ResolvedRecipient]:
        return list(self.recipients)


@dataclass
class _Campaigns:
    saved: list[Campaign] = field(default_factory=list)

    async def save(self, campaign: Campaign) -> None:
        self.saved = [c for c in self.saved if c.campaign_id != campaign.campaign_id]
        self.saved.append(campaign)

    async def get(self, campaign_id: str) -> Campaign | None:
        return next((c for c in self.saved if c.campaign_id == campaign_id), None)

    async def try_claim(self, campaign: Campaign) -> bool:
        if any(c.idempotency_key == campaign.idempotency_key for c in self.saved):
            return False
        self.saved.append(campaign)
        return True

    async def get_by_idempotency_key(self, idempotency_key: str) -> Campaign | None:
        return next((c for c in self.saved if c.idempotency_key == idempotency_key), None)


@dataclass
class _Deliveries:
    rows: dict[str, Delivery] = field(default_factory=dict)

    async def save_many(self, deliveries: list[Delivery]) -> None:
        for d in deliveries:
            self.rows[d.delivery_id] = d

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]:
        return [d for d in self.rows.values() if d.campaign_id == campaign_id]


@pytest.mark.asyncio
async def test_campaign_to_a_suppressed_recipient_is_skipped_and_recorded(db) -> None:
    """The skipped recipient must be visible in the delivery log, not vanish."""
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)

    deliveries = _Deliveries()
    use_case = SendCampaign(
        campaigns=_Campaigns(),
        deliveries=deliveries,
        resolver=_Resolver(
            [
                ResolvedRecipient(user_id="u-dead", email=BOUNCED),
                ResolvedRecipient(user_id="u-live", email="live@example.com"),
            ]
        ),
        sender=gated,
    )

    result = await use_case.execute(
        SendCampaignCommand(
            academy_id="acad-a",
            sender_id="admin-1",
            audience=AcademyAudience(role="parent"),
            subject="Summer camp",
            body="<p>hi</p>",
        )
    )

    assert result.sent_count == 1
    assert result.failed_count == 1
    assert [row["email"] for row in stub.sent] == ["live@example.com"]

    rows = {d.recipient_user_id: d for d in await deliveries.list_for_campaign(result.campaign_id)}
    assert rows["u-dead"].status is DeliveryStatus.FAILED
    assert rows["u-dead"].failed_reason == "suppressed:hard_bounce"
    assert rows["u-live"].status is DeliveryStatus.SENT


@dataclass
class _DigestSends:
    rows: dict[str, DigestSend] = field(default_factory=dict)
    failures: list[tuple[str, str, bool]] = field(default_factory=list)

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None:
        key = f"{academy_id}:{coach_id}:{digest_date}"
        if key in self.rows:
            return None
        send = DigestSend.queued(
            digest_id=key,
            academy_id=academy_id,
            coach_id=coach_id,
            digest_date=digest_date,
            coach_email=BOUNCED,
            created_at=datetime.now(UTC),
        )
        self.rows[key] = send
        return send

    async def record_test_send(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend:  # pragma: no cover - unused here
        raise NotImplementedError

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None:
        self.rows[digest_id] = self.rows[digest_id].mark_sent(
            provider_message_id=provider_message_id, sent_at=datetime.now(UTC)
        )

    async def mark_failed(self, digest_id: str, reason: str, *, retryable: bool = True) -> None:
        self.failures.append((digest_id, reason, retryable))

    async def mark_skipped_empty(self, digest_id: str) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def list_recent(self, academy_id: str, limit: int) -> list[DigestSend]:
        return list(self.rows.values())[:limit]


class _Plan:
    def __init__(self) -> None:
        self.sessions = [type("S", (), {"groups": ["g"], "unplaced": []})()]


class _PlanProvider:
    async def execute(self, coach_id: str, on_date: date) -> Any:
        return _Plan()


@pytest.mark.asyncio
async def test_digest_to_a_suppressed_coach_is_skipped_and_recorded(db) -> None:
    gated, stub, repo = await _gated(db)
    await repo.record(email=BOUNCED, reason=SuppressionReason.HARD_BOUNCE)

    digests = _DigestSends()
    use_case = SendCoachDailyDigest(
        digests=digests,
        resolver=_Resolver([ResolvedRecipient(user_id="coach-1", email=BOUNCED)]),
        sender=gated,
        plan_provider=_PlanProvider(),
    )

    result = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id="acad-a", digest_date=date(2026, 8, 31))
    )

    assert result.sent == 0
    assert result.failed == 1
    assert stub.sent == []
    assert digests.failures == [("acad-a:coach-1:2026-08-31", "suppressed:hard_bounce", True)]
