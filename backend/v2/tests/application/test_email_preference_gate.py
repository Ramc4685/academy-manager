"""Recipient unsubscribe preferences at send time (#555).

These exercise the real seam end-to-end: a real Mongo-backed
``MongoEmailPreferenceGate``, wrapped by the real ``GatedEmailSendPort``, wired
into the real send loops. Nothing here stubs the gate itself, because the bug
this issue fixes was the *absence* of a check, not a wrong one.

The compliance-critical case is
``test_transactional_email_is_never_blocked_by_an_unsubscribe``: an opt-out
that silenced a family's invoice would turn a marketing preference into a
billing incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaign,
    SendCampaignCommand,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_daily_digest import (
    SendParentDailyDigest,
    SendParentDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Campaign,
    Delivery,
    DeliveryStatus,
)
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
    MongoEmailPreferenceGate,
    MongoEmailPreferenceRepository,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-pref"


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["email-preferences"]


def _recipient(user_id: str, email: str) -> ResolvedRecipient:
    return ResolvedRecipient(user_id=user_id, email=email, display_name=user_id)


async def _opt_out(db: Any, user_id: str, *, campaigns: bool, digests: bool) -> None:
    with tenant_scope(ACADEMY):
        await MongoEmailPreferenceRepository(db).set_opt_outs(
            user_id=user_id,
            email=f"{user_id}@example.test",
            campaigns_opted_out=campaigns,
            digests_opted_out=digests,
            source="link",
        )


def _gated(db: Any, inner: StubEmailSendPort) -> GatedEmailSendPort:
    return GatedEmailSendPort(inner=inner, preferences=MongoEmailPreferenceGate(db))


# ---------------------------------------------------------------------------
# Fakes for the parts of the loops that are not under test
# ---------------------------------------------------------------------------


@dataclass
class _Resolver:
    recipients: list[ResolvedRecipient] = field(default_factory=list)

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return list(self.recipients)

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


@dataclass
class _Campaigns:
    saved: list[Campaign] = field(default_factory=list)
    claimed: dict[str, Campaign] = field(default_factory=dict)

    async def save(self, campaign: Campaign) -> None:
        self.saved.append(campaign)

    async def get(self, campaign_id: str) -> Campaign | None:
        return None

    async def try_claim(self, campaign: Campaign) -> bool:
        if campaign.idempotency_key in self.claimed:
            return False
        self.claimed[campaign.idempotency_key or ""] = campaign
        return True

    async def get_by_idempotency_key(self, idempotency_key: str) -> Campaign | None:
        return self.claimed.get(idempotency_key)


@dataclass
class _Deliveries:
    batches: list[list[Delivery]] = field(default_factory=list)

    async def save_many(self, deliveries: list[Delivery]) -> None:
        self.batches.append(list(deliveries))

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]:
        return list(self.batches[-1]) if self.batches else []

    @property
    def final(self) -> list[Delivery]:
        return self.batches[-1]


@dataclass
class _DigestSends:
    """Just enough of DigestSendRepository to observe the failure bucket."""

    claims: dict[str, str] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    async def try_claim(self, academy_id: str, coach_id: str, digest_date: str) -> Any:
        digest_id = f"dg-{coach_id}"
        if digest_id in self.claims:
            return None
        self.claims[digest_id] = coach_id
        return SimpleNamespace(digest_id=digest_id)

    async def record_test_send(self, academy_id: str, coach_id: str, digest_date: str) -> Any:
        return SimpleNamespace(digest_id=f"dg-test-{coach_id}")

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None:
        self.sent.append(digest_id)

    async def mark_failed(self, digest_id: str, reason: str, *, retryable: bool = True) -> None:
        self.failures.append({"digest_id": digest_id, "reason": reason, "retryable": retryable})

    async def mark_skipped_empty(self, digest_id: str) -> None:
        self.skipped.append(digest_id)

    async def list_recent(self, academy_id: str, limit: int) -> list[Any]:
        return []


@dataclass
class _ParentViews:
    async def build_view(self, parent_id: str, on_date: date) -> ParentDigestView | None:
        return ParentDigestView(
            parent_name="Parent",
            date_label="Saturday, June 13",
            program_name="Badminton",
            children=(
                ChildDigestView(
                    child_name="Kid",
                    session_time="6:00 - 6:45 PM",
                    session_label="Beginner",
                ),
            ),
            on_portal=True,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_campaign_to_opted_out_recipient_is_not_sent(db: Any) -> None:
    await _opt_out(db, "p-out", campaigns=True, digests=False)

    stub = StubEmailSendPort()
    deliveries = _Deliveries()
    use_case = SendCampaign(
        campaigns=_Campaigns(),
        deliveries=deliveries,
        resolver=_Resolver(
            [_recipient("p-in", "p-in@example.test"), _recipient("p-out", "p-out@example.test")]
        ),
        sender=_gated(db, stub),
    )

    with tenant_scope(ACADEMY):
        result = await use_case.execute(
            SendCampaignCommand(
                academy_id=ACADEMY,
                sender_id="admin-1",
                audience=AcademyAudience(role="parent"),
                subject="Summer camp",
                body="<p>Sign up now</p>",
            )
        )

    emailed = {row["user_id"] for row in stub.sent}
    assert emailed == {"p-in"}, "an opted-out parent was still emailed the campaign"
    assert result.sent_count == 1
    assert result.failed_count == 1

    # The skip is *recorded*, not dropped: an admin looking at the delivery log
    # must be able to see why someone in the audience got nothing.
    blocked = next(d for d in deliveries.final if d.recipient_user_id == "p-out")
    assert blocked.status is DeliveryStatus.FAILED
    assert blocked.failed_reason == "unsubscribed:campaign"


@pytest.mark.asyncio
async def test_transactional_email_is_never_blocked_by_an_unsubscribe(db: Any) -> None:
    """COMPLIANCE-CRITICAL. Opting out of marketing must not stop an invoice.

    Every transactional adapter (invoice, dunning, login invite, dues reminder,
    add-card reminder) calls ``send`` without a ``category``, so this exercises
    exactly the call shape they use.
    """
    await _opt_out(db, "p-out", campaigns=True, digests=True)

    stub = StubEmailSendPort()
    gated = _gated(db, stub)

    with tenant_scope(ACADEMY):
        outcome = await gated.send(
            recipient=_recipient("p-out", "p-out@example.test"),
            subject="Your invoice for June",
            body="<p>Amount due: $60.00</p>",
        )

    assert outcome.ok, "an unsubscribe silenced a transactional email"
    assert outcome.suppressed is False
    assert [row["user_id"] for row in stub.sent] == ["p-out"]
    assert stub.sent[0]["category"] is EmailCategory.TRANSACTIONAL


@pytest.mark.asyncio
async def test_digest_to_opted_out_parent_is_marked_failed_non_retryable(db: Any) -> None:
    """A suppressed digest must not be re-claimed by the next hourly tick."""
    await _opt_out(db, "p-out", campaigns=False, digests=True)

    stub = StubEmailSendPort()
    digests = _DigestSends()
    use_case = SendParentDailyDigest(
        digests=digests,
        resolver=_Resolver([_recipient("p-out", "p-out@example.test")]),
        sender=_gated(db, stub),
        provider=_ParentViews(),
    )

    with tenant_scope(ACADEMY):
        result = await use_case.execute(
            SendParentDailyDigestCommand(academy_id=ACADEMY, digest_date=date(2026, 6, 13))
        )

    assert stub.sent == [], "an opted-out parent was still emailed the daily digest"
    assert result.sent == 0
    assert result.failed == 1
    assert digests.failures == [
        {"digest_id": "dg-p-out", "reason": "unsubscribed:digest", "retryable": False}
    ]


@pytest.mark.asyncio
async def test_an_opt_out_of_campaigns_does_not_silence_digests(db: Any) -> None:
    """The two switches are independent — one opt-out must not imply the other."""
    await _opt_out(db, "p-out", campaigns=True, digests=False)

    stub = StubEmailSendPort()
    use_case = SendParentDailyDigest(
        digests=_DigestSends(),
        resolver=_Resolver([_recipient("p-out", "p-out@example.test")]),
        sender=_gated(db, stub),
        provider=_ParentViews(),
    )

    with tenant_scope(ACADEMY):
        result = await use_case.execute(
            SendParentDailyDigestCommand(academy_id=ACADEMY, digest_date=date(2026, 6, 13))
        )

    assert result.sent == 1
    assert [row["user_id"] for row in stub.sent] == ["p-out"]


@pytest.mark.asyncio
async def test_a_gate_outage_allows_rather_than_silently_stopping_all_mail(db: Any) -> None:
    """The #435 lesson: email that fails quietly stays broken for weeks."""

    class _Exploding:
        async def get(self, user_id: str) -> Any:
            raise RuntimeError("mongo is down")

    gate = MongoEmailPreferenceGate(db)
    gate._repo = _Exploding()  # type: ignore[assignment]
    stub = StubEmailSendPort()
    gated = GatedEmailSendPort(inner=stub, preferences=gate)

    outcome = await gated.send(
        recipient=_recipient("p-1", "p-1@example.test"),
        subject="Newsletter",
        body="<p>hi</p>",
        category=EmailCategory.CAMPAIGN,
    )

    assert outcome.ok
    assert len(stub.sent) == 1


@pytest.mark.asyncio
async def test_a_recipient_can_opt_back_in(db: Any) -> None:
    await _opt_out(db, "p-1", campaigns=True, digests=True)
    await _opt_out(db, "p-1", campaigns=False, digests=False)

    stub = StubEmailSendPort()
    with tenant_scope(ACADEMY):
        outcome: SendOutcome = await _gated(db, stub).send(
            recipient=_recipient("p-1", "p-1@example.test"),
            subject="Summer camp",
            body="<p>hi</p>",
            category=EmailCategory.CAMPAIGN,
        )

    assert outcome.ok
    assert len(stub.sent) == 1
