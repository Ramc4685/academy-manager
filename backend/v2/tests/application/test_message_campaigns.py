"""Message campaign + delivery use-case behavior (Wave 4 messaging slice).

These tests cover the audience targeting model and per-recipient delivery
resolution / state recording. Email sending uses a stub send port so that no
real provider call is made.

Acceptance criteria (from docs/plans/2026-05-21-saas-v2-parallel-execution-plan.md
Stream L):

- Campaigns support academy, session, parent, coach, selected family,
  and payment-risk audiences.
- Deliveries record per-recipient state.
- Direct messages resolve recipients by search, not typed IDs (modelled here
  as the SelectedRecipientsAudience consuming pre-resolved user_ids).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    CampaignRepository,
    DeliveryRepository,
    EmailSendPort,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaign,
    SendCampaignCommand,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.errors import (
    EmptyAudienceError,
    InvalidAudienceError,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Campaign,
    CampaignStatus,
    CoachAudience,
    Delivery,
    DeliveryStatus,
    PaymentRiskAudience,
    SelectedRecipientsAudience,
    SessionAudience,
    parse_audience,
)

# ---------------------------------------------------------------------------
# Fake adapters
# ---------------------------------------------------------------------------


@dataclass
class FakeAudienceResolver(AudienceResolver):
    """In-memory resolver. Tests pre-seed recipients per audience shape."""

    by_academy: list[ResolvedRecipient] = field(default_factory=list)
    by_session: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    by_coach_session: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    all_coaches: list[ResolvedRecipient] = field(default_factory=list)
    payment_risk: list[ResolvedRecipient] = field(default_factory=list)
    selected: dict[str, ResolvedRecipient] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        self.calls.append(("academy", {"role": audience.role}))
        if audience.role == "coach":
            return list(self.all_coaches)
        return list(self.by_academy)

    async def resolve_session_audience(self, audience: SessionAudience) -> list[ResolvedRecipient]:
        self.calls.append(("session", {"session_id": audience.session_id}))
        return list(self.by_session.get(audience.session_id, []))

    async def resolve_coach_audience(self, audience: CoachAudience) -> list[ResolvedRecipient]:
        self.calls.append(("coach", {"session_id": audience.session_id}))
        if audience.session_id is None:
            return list(self.all_coaches)
        return list(self.by_coach_session.get(audience.session_id, []))

    async def resolve_selected_audience(
        self, audience: SelectedRecipientsAudience
    ) -> list[ResolvedRecipient]:
        self.calls.append(("selected", {"user_ids": list(audience.user_ids)}))
        return [self.selected[u] for u in audience.user_ids if u in self.selected]

    async def resolve_payment_risk_audience(
        self, audience: PaymentRiskAudience
    ) -> list[ResolvedRecipient]:
        self.calls.append(("payment_risk", {"min_days_overdue": audience.min_days_overdue}))
        return list(self.payment_risk)


@dataclass
class StubEmailSendPort(EmailSendPort):
    """Stub send port. Records sends; never touches a real provider.

    Per docs/agent/backend-api-rules.md: do not send real email from test/local.
    """

    sent: list[dict[str, Any]] = field(default_factory=list)
    fail_for_emails: set[str] = field(default_factory=set)

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome:
        record = {
            "user_id": recipient.user_id,
            "email": recipient.email,
            "subject": subject,
            "body": body,
        }
        self.sent.append(record)
        if recipient.email in self.fail_for_emails:
            return SendOutcome(
                ok=False,
                provider_message_id=None,
                failed_reason="bounced",
            )
        return SendOutcome(
            ok=True,
            provider_message_id=f"prov-{len(self.sent):04d}",
            failed_reason=None,
        )


@dataclass
class InMemoryCampaignRepository(CampaignRepository):
    saved: list[Campaign] = field(default_factory=list)

    async def save(self, campaign: Campaign) -> None:
        # mimic upsert
        self.saved = [c for c in self.saved if c.campaign_id != campaign.campaign_id]
        self.saved.append(campaign)

    async def get(self, campaign_id: str) -> Campaign | None:
        for c in self.saved:
            if c.campaign_id == campaign_id:
                return c
        return None

    async def try_claim(self, campaign: Campaign) -> bool:
        # mimic the unique (academy_id, idempotency_key) index
        assert campaign.idempotency_key, "try_claim requires an idempotency_key"
        for c in self.saved:
            if (
                c.idempotency_key == campaign.idempotency_key
                and c.academy_id == campaign.academy_id
            ):
                return False
        self.saved.append(campaign)
        return True

    async def get_by_idempotency_key(self, idempotency_key: str) -> Campaign | None:
        for c in self.saved:
            if c.idempotency_key == idempotency_key:
                return c
        return None


@dataclass
class InMemoryDeliveryRepository(DeliveryRepository):
    saved: list[Delivery] = field(default_factory=list)

    async def save_many(self, deliveries: list[Delivery]) -> None:
        # mimic upsert keyed by delivery_id
        incoming = {d.delivery_id for d in deliveries}
        self.saved = [d for d in self.saved if d.delivery_id not in incoming]
        self.saved.extend(deliveries)

    async def list_for_campaign(self, campaign_id: str) -> list[Delivery]:
        return [d for d in self.saved if d.campaign_id == campaign_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recipient(user_id: str, email: str | None = None) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id=user_id,
        email=email or f"{user_id}@example.test",
        display_name=user_id.title(),
    )


def _build_use_case(
    *,
    resolver: FakeAudienceResolver | None = None,
    sender: StubEmailSendPort | None = None,
) -> tuple[
    SendCampaign,
    FakeAudienceResolver,
    StubEmailSendPort,
    InMemoryCampaignRepository,
    InMemoryDeliveryRepository,
]:
    resolver = resolver or FakeAudienceResolver()
    sender = sender or StubEmailSendPort()
    campaigns = InMemoryCampaignRepository()
    deliveries = InMemoryDeliveryRepository()
    use_case = SendCampaign(
        campaigns=campaigns,
        deliveries=deliveries,
        resolver=resolver,
        sender=sender,
        now=lambda: datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        new_id=_counter_ids(),
    )
    return use_case, resolver, sender, campaigns, deliveries


def _counter_ids():
    counter = {"n": 0}

    def next_id() -> str:
        counter["n"] += 1
        return f"id-{counter['n']:04d}"

    return next_id


# ---------------------------------------------------------------------------
# Audience model shape
# ---------------------------------------------------------------------------


class TestAudienceParsing:
    def test_parse_academy_audience(self) -> None:
        a = parse_audience({"type": "academy", "role": "parent"})
        assert isinstance(a, AcademyAudience)
        assert a.role == "parent"

    def test_parse_session_audience_requires_session_id(self) -> None:
        a = parse_audience({"type": "session", "session_id": "sess-1"})
        assert isinstance(a, SessionAudience)
        assert a.session_id == "sess-1"

    def test_parse_coach_audience_session_id_optional(self) -> None:
        a1 = parse_audience({"type": "coach"})
        a2 = parse_audience({"type": "coach", "session_id": "sess-2"})
        assert isinstance(a1, CoachAudience)
        assert a1.session_id is None
        assert isinstance(a2, CoachAudience)
        assert a2.session_id == "sess-2"

    def test_parse_selected_audience_requires_user_ids(self) -> None:
        a = parse_audience({"type": "selected", "user_ids": ["u-1", "u-2"]})
        assert isinstance(a, SelectedRecipientsAudience)
        assert a.user_ids == ("u-1", "u-2")

    def test_parse_selected_audience_rejects_empty_user_ids(self) -> None:
        with pytest.raises(InvalidAudienceError):
            parse_audience({"type": "selected", "user_ids": []})

    def test_parse_payment_risk_audience_default_overdue(self) -> None:
        a = parse_audience({"type": "payment_risk"})
        assert isinstance(a, PaymentRiskAudience)
        assert a.min_days_overdue == 1

    def test_parse_payment_risk_audience_custom_overdue(self) -> None:
        a = parse_audience({"type": "payment_risk", "min_days_overdue": 14})
        assert isinstance(a, PaymentRiskAudience)
        assert a.min_days_overdue == 14

    def test_parse_unknown_audience_type_raises(self) -> None:
        with pytest.raises(InvalidAudienceError):
            parse_audience({"type": "completely-made-up"})

    def test_parse_session_audience_missing_session_id_raises(self) -> None:
        with pytest.raises(InvalidAudienceError):
            parse_audience({"type": "session"})


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


class TestCampaignDomain:
    def test_campaign_starts_in_draft(self) -> None:
        campaign = Campaign.new(
            campaign_id="c-1",
            academy_id="aca-1",
            sender_id="u-admin",
            audience=AcademyAudience(role="parent"),
            subject="Welcome",
            body="Body",
            created_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        )
        assert campaign.status == CampaignStatus.DRAFT
        assert campaign.sent_at is None
        assert campaign.academy_id == "aca-1"

    def test_delivery_records_per_recipient_state(self) -> None:
        d = Delivery.queued(
            delivery_id="d-1",
            academy_id="aca-1",
            campaign_id="c-1",
            recipient=_recipient("u-1", "u1@example.test"),
        )
        assert d.status == DeliveryStatus.QUEUED
        assert d.recipient_user_id == "u-1"
        assert d.recipient_email == "u1@example.test"
        assert d.academy_id == "aca-1"
        assert d.sent_at is None

        sent = d.mark_sent(
            provider_message_id="prov-1",
            sent_at=datetime(2026, 5, 21, 12, 30, tzinfo=UTC),
        )
        assert sent.status == DeliveryStatus.SENT
        assert sent.provider_message_id == "prov-1"
        assert sent.failed_reason is None

        failed = d.mark_failed(reason="bounced")
        assert failed.status == DeliveryStatus.FAILED
        assert failed.failed_reason == "bounced"
        assert failed.provider_message_id is None


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------


class TestRecipientResolution:
    @pytest.mark.asyncio
    async def test_academy_parent_audience_resolves_all_parents(self) -> None:
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1"), _recipient("p-2"), _recipient("p-3")]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Hello",
            )
        )

        assert result.total_recipients == 3
        assert result.sent_count == 3
        assert result.failed_count == 0
        assert {d.recipient_user_id for d in deliveries.saved} == {"p-1", "p-2", "p-3"}
        assert all(d.status == DeliveryStatus.SENT for d in deliveries.saved)
        assert resolver.calls[0] == ("academy", {"role": "parent"})

    @pytest.mark.asyncio
    async def test_duplicate_recipients_are_deduped_before_send(self) -> None:
        """Belt-and-suspenders send-time dedup (#520): a person resolved twice
        — same user_id, or a second doc matched via auth_uid carrying a
        different user_id but the same email — gets exactly one email and one
        delivery row."""
        use_case, resolver, sender, _campaigns, deliveries = _build_use_case()
        resolver.by_academy = [
            _recipient("p-1", email="parent-one@example.test"),
            _recipient("p-1", email="parent-one@example.test"),  # same user_id
            _recipient("auth-uid-p1", email="Parent-One@Example.test"),  # same email
            _recipient("p-2"),
        ]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Hello",
            )
        )

        assert result.total_recipients == 2
        assert result.sent_count == 2
        assert [s["user_id"] for s in sender.sent] == ["p-1", "p-2"]
        assert {d.recipient_user_id for d in deliveries.saved} == {"p-1", "p-2"}

    @pytest.mark.asyncio
    async def test_recipients_without_email_dedupe_only_by_user_id(self) -> None:
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.by_academy = [
            ResolvedRecipient(user_id="p-1", email=None),
            ResolvedRecipient(user_id="p-1", email=None),
            ResolvedRecipient(user_id="p-2", email=None),
        ]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Hello",
            )
        )

        assert result.total_recipients == 2
        assert {d.recipient_user_id for d in deliveries.saved} == {"p-1", "p-2"}

    @pytest.mark.asyncio
    async def test_session_audience_resolves_session_parents(self) -> None:
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.by_session = {
            "sess-1": [_recipient("p-1"), _recipient("p-2")],
            "sess-2": [_recipient("p-9")],
        }

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=SessionAudience(session_id="sess-1"),
                subject="Practice change",
                body="Body",
            )
        )

        assert result.total_recipients == 2
        assert {d.recipient_user_id for d in deliveries.saved} == {"p-1", "p-2"}

    @pytest.mark.asyncio
    async def test_coach_audience_without_session_resolves_all_coaches(self) -> None:
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.all_coaches = [_recipient("c-1"), _recipient("c-2")]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=CoachAudience(session_id=None),
                subject="Schedule",
                body="Body",
            )
        )

        assert result.total_recipients == 2
        assert {d.recipient_user_id for d in deliveries.saved} == {"c-1", "c-2"}

    @pytest.mark.asyncio
    async def test_coach_audience_with_session_resolves_only_session_coaches(self) -> None:
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.by_coach_session = {"sess-1": [_recipient("c-1")]}
        resolver.all_coaches = [_recipient("c-1"), _recipient("c-2")]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=CoachAudience(session_id="sess-1"),
                subject="Sub needed",
                body="Body",
            )
        )

        assert result.total_recipients == 1
        assert deliveries.saved[0].recipient_user_id == "c-1"

    @pytest.mark.asyncio
    async def test_selected_recipients_audience_resolves_specific_users(self) -> None:
        # Direct messages must arrive at pre-resolved user IDs. Admins reach
        # this audience via a name/email search UI, never by typing raw IDs.
        use_case, resolver, _sender, _campaigns, deliveries = _build_use_case()
        resolver.selected = {
            "u-7": _recipient("u-7", "seven@example.test"),
            "u-9": _recipient("u-9", "nine@example.test"),
        }

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=SelectedRecipientsAudience(user_ids=("u-7", "u-9")),
                subject="Direct",
                body="Body",
            )
        )

        assert result.total_recipients == 2
        assert {d.recipient_email for d in deliveries.saved} == {
            "seven@example.test",
            "nine@example.test",
        }

    @pytest.mark.asyncio
    async def test_payment_risk_audience_resolves_risk_families(self) -> None:
        use_case, resolver, _sender, _campaigns, _deliveries = _build_use_case()
        resolver.payment_risk = [_recipient("p-late-1"), _recipient("p-late-2")]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=PaymentRiskAudience(min_days_overdue=7),
                subject="Reminder",
                body="Body",
            )
        )

        assert result.total_recipients == 2
        assert resolver.calls[0] == ("payment_risk", {"min_days_overdue": 7})

    @pytest.mark.asyncio
    async def test_empty_audience_raises(self) -> None:
        use_case, _, _, _, _ = _build_use_case()
        with pytest.raises(EmptyAudienceError):
            await use_case.execute(
                SendCampaignCommand(
                    academy_id="aca-1",
                    sender_id="u-admin",
                    audience=AcademyAudience(role="parent"),
                    subject="Hi",
                    body="Body",
                )
            )


# ---------------------------------------------------------------------------
# Delivery state recording
# ---------------------------------------------------------------------------


class TestDeliveryRecording:
    @pytest.mark.asyncio
    async def test_partial_failure_records_each_recipient_status(self) -> None:
        sender = StubEmailSendPort(fail_for_emails={"p-2@example.test"})
        use_case, resolver, _, _campaigns, deliveries = _build_use_case(sender=sender)
        resolver.by_academy = [
            _recipient("p-1", "p-1@example.test"),
            _recipient("p-2", "p-2@example.test"),
            _recipient("p-3", "p-3@example.test"),
        ]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Body",
            )
        )

        assert result.total_recipients == 3
        assert result.sent_count == 2
        assert result.failed_count == 1
        by_user = {d.recipient_user_id: d for d in deliveries.saved}
        assert by_user["p-1"].status == DeliveryStatus.SENT
        assert by_user["p-2"].status == DeliveryStatus.FAILED
        assert by_user["p-2"].failed_reason == "bounced"
        assert by_user["p-3"].status == DeliveryStatus.SENT
        # No real email leaves the system.
        assert all(rec["email"].endswith("@example.test") for rec in sender.sent)

    @pytest.mark.asyncio
    async def test_campaign_status_advances_to_sent_after_send(self) -> None:
        use_case, resolver, _, campaigns, _deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1")]

        result = await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-1",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Body",
            )
        )

        stored = await campaigns.get(result.campaign_id)
        assert stored is not None
        assert stored.status == CampaignStatus.SENT
        assert stored.sent_at == datetime(2026, 5, 21, 12, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_every_delivery_carries_academy_id(self) -> None:
        use_case, resolver, _, _, deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1"), _recipient("p-2")]

        await use_case.execute(
            SendCampaignCommand(
                academy_id="aca-42",
                sender_id="u-admin",
                audience=AcademyAudience(role="parent"),
                subject="Hi",
                body="Body",
            )
        )

        assert all(d.academy_id == "aca-42" for d in deliveries.saved)


# ---------------------------------------------------------------------------
# Idempotency (#512): a retried POST must not re-email the audience
# ---------------------------------------------------------------------------


def _parent_command(**overrides: Any) -> SendCampaignCommand:
    base: dict[str, Any] = {
        "academy_id": "aca-1",
        "sender_id": "u-admin",
        "audience": AcademyAudience(role="parent"),
        "subject": "Hi",
        "body": "Hello",
    }
    base.update(overrides)
    return SendCampaignCommand(**base)


class TestCampaignIdempotency:
    @pytest.mark.asyncio
    async def test_identical_retry_sends_nothing_and_returns_same_campaign(self) -> None:
        use_case, resolver, sender, _campaigns, deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1"), _recipient("p-2")]

        first = await use_case.execute(_parent_command())
        assert first.deduplicated is False
        assert len(sender.sent) == 2

        retry = await use_case.execute(_parent_command())

        assert retry.deduplicated is True
        assert retry.campaign_id == first.campaign_id
        assert retry.total_recipients == 2
        assert retry.sent_count == 2
        assert retry.failed_count == 0
        # No additional email left the system on the retry.
        assert len(sender.sent) == 2
        assert len(deliveries.saved) == 2

    @pytest.mark.asyncio
    async def test_different_content_is_a_new_campaign(self) -> None:
        use_case, resolver, sender, _campaigns, _deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1")]

        first = await use_case.execute(_parent_command())
        second = await use_case.execute(_parent_command(body="A different body"))

        assert second.campaign_id != first.campaign_id
        assert second.deduplicated is False
        assert len(sender.sent) == 2

    @pytest.mark.asyncio
    async def test_client_supplied_key_dedupes_even_when_content_differs(self) -> None:
        use_case, resolver, sender, _campaigns, _deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1")]

        first = await use_case.execute(_parent_command(idempotency_key="client-key-1"))
        retry = await use_case.execute(
            _parent_command(body="Edited before retry", idempotency_key="client-key-1")
        )

        assert retry.deduplicated is True
        assert retry.campaign_id == first.campaign_id
        assert len(sender.sent) == 1

    @pytest.mark.asyncio
    async def test_campaign_row_carries_idempotency_key(self) -> None:
        use_case, resolver, _sender, campaigns, _deliveries = _build_use_case()
        resolver.by_academy = [_recipient("p-1")]

        result = await use_case.execute(_parent_command(idempotency_key="client-key-9"))

        stored = await campaigns.get(result.campaign_id)
        assert stored is not None
        assert stored.idempotency_key == "client-key-9"


# ---------------------------------------------------------------------------
# Crash visibility (#512): QUEUED rows are persisted before the send loop
# ---------------------------------------------------------------------------


@dataclass
class CrashingSendPort(EmailSendPort):
    """Sends successfully until `crash_on_email`, then raises mid-loop."""

    crash_on_email: str
    sent: list[str] = field(default_factory=list)

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome:
        if recipient.email == self.crash_on_email:
            raise RuntimeError("process died mid-loop")
        self.sent.append(recipient.email or "")
        return SendOutcome(
            ok=True, provider_message_id=f"prov-{len(self.sent)}", failed_reason=None
        )


class TestCrashVisibility:
    @pytest.mark.asyncio
    async def test_queued_batch_is_persisted_before_any_send(self) -> None:
        resolver = FakeAudienceResolver()
        resolver.by_academy = [
            _recipient("p-1", "p-1@example.test"),
            _recipient("p-2", "p-2@example.test"),
            _recipient("p-3", "p-3@example.test"),
        ]
        crasher = CrashingSendPort(crash_on_email="p-2@example.test")
        campaigns = InMemoryCampaignRepository()
        deliveries = InMemoryDeliveryRepository()
        use_case = SendCampaign(
            campaigns=campaigns,
            deliveries=deliveries,
            resolver=resolver,
            sender=crasher,
            now=lambda: datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
            new_id=_counter_ids(),
        )

        with pytest.raises(RuntimeError):
            await use_case.execute(_parent_command())

        # The whole roster is visible as QUEUED rows even though the loop died,
        # and the campaign is inspectable in SENDING — not invisibly half-sent.
        assert len(deliveries.saved) == 3
        assert all(d.status == DeliveryStatus.QUEUED for d in deliveries.saved)
        assert campaigns.saved[0].status == CampaignStatus.SENDING


# ---------------------------------------------------------------------------
# Smoke check that the use case never touches a real provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_port_is_the_only_outbound_path() -> None:
    """Wave-4 safety: no other outbound channel exists in this slice."""
    use_case, resolver, sender, _, _ = _build_use_case()
    resolver.by_academy = [_recipient("p-1")]

    await use_case.execute(
        SendCampaignCommand(
            academy_id="aca-1",
            sender_id="u-admin",
            audience=AcademyAudience(role="parent"),
            subject="Subject",
            body="Body",
        )
    )

    # The stub captured the single outbound attempt; nothing else is wired.
    assert len(sender.sent) == 1
    assert sender.sent[0]["subject"] == "Subject"
