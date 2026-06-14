"""SendCoachDigestTest use case.

A test send must (a) bypass the daily idempotency claim — recorded as a
``kind="test"`` row via ``record_test_send`` — and (b) reuse the same renderer
and plan provider as the daily digest. A stub send port is used so no provider
is contacted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    CoachDigestTargetNotFound,
    SendCoachDigestTest,
    SendCoachDigestTestCommand,
)
from backend.v2.contexts.communications.domain.models import DigestSend, DigestSendStatus

ACADEMY_ID = "acad-1"
ON_DATE = date(2026, 6, 13)


@dataclass
class FakeDigestSendRepository:
    by_id: dict[str, DigestSend] = field(default_factory=dict)
    claim_calls: int = 0
    test_calls: list[tuple[str, str, str]] = field(default_factory=list)
    _counter: int = 0

    async def try_claim(self, academy_id, coach_id, digest_date):
        self.claim_calls += 1
        return None  # would block — must never be called by the test send

    async def record_test_send(self, academy_id, coach_id, digest_date):
        self.test_calls.append((academy_id, coach_id, digest_date))
        self._counter += 1
        digest = DigestSend.queued(
            digest_id=f"test-{self._counter:04d}",
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime(2026, 6, 13, tzinfo=UTC),
            kind="test",
        )
        self.by_id[digest.digest_id] = digest
        return digest

    async def mark_sent(self, digest_id, provider_message_id):
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_sent(provider_message_id=provider_message_id, sent_at="now")

    async def mark_failed(self, digest_id, reason):
        self.by_id[digest_id] = self.by_id[digest_id].mark_failed(reason=reason)

    async def mark_skipped_empty(self, digest_id):
        self.by_id[digest_id] = self.by_id[digest_id].mark_skipped_empty()

    async def list_recent(self, academy_id, limit):
        return list(self.by_id.values())[:limit]


@dataclass
class FakeSelectedResolver(AudienceResolver):
    users: dict[str, ResolvedRecipient] = field(default_factory=dict)

    async def resolve_academy_audience(self, audience):
        return []

    async def resolve_session_audience(self, audience):
        return []

    async def resolve_coach_audience(self, audience):
        return []

    async def resolve_selected_audience(self, audience):
        return [self.users[uid] for uid in audience.user_ids if uid in self.users]

    async def resolve_payment_risk_audience(self, audience):
        return []


@dataclass
class StubSendPort:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(self, *, recipient, subject, body):
        self.sent.append({"email": recipient.email, "subject": subject})
        return SendOutcome(
            ok=True, provider_message_id=f"stub-{len(self.sent)}", failed_reason=None
        )


@dataclass
class FakePlanProvider:
    plan: Any = None

    async def execute(self, coach_id, on_date):
        return self.plan


def _populated_plan() -> Any:
    student = SimpleNamespace(student_name="Alice", focus="Clear", next_skill=None)
    group = SimpleNamespace(level_name="Level 1", students=[student], youtube_links=[])
    session = SimpleNamespace(
        title="Juniors", location="Court A", start_at=None, end_at=None, groups=[group], unplaced=[]
    )
    return SimpleNamespace(date="2026-06-13", program_name="Badminton", sessions=[session])


def _build(plan, coach_id="coach-1", email="c1@example.test"):
    digests = FakeDigestSendRepository()
    resolver = FakeSelectedResolver(
        users={coach_id: ResolvedRecipient(user_id=coach_id, email=email, display_name="Coach")}
    )
    sender = StubSendPort()
    use_case = SendCoachDigestTest(
        digests=digests,
        resolver=resolver,
        sender=sender,
        plan_provider=FakePlanProvider(plan=plan),
    )
    return use_case, digests, sender


@pytest.mark.asyncio
async def test_test_send_records_kind_test_and_emails_without_claiming() -> None:
    use_case, digests, sender = _build(_populated_plan())

    result = await use_case.execute(
        SendCoachDigestTestCommand(academy_id=ACADEMY_ID, target_user_id="coach-1", on_date=ON_DATE)
    )

    assert result.status == "sent"
    assert result.email == "c1@example.test"
    assert digests.claim_calls == 0  # never consumes the daily claim
    assert digests.test_calls == [(ACADEMY_ID, "coach-1", "2026-06-13")]
    assert len(sender.sent) == 1
    row = next(iter(digests.by_id.values()))
    assert row.kind == "test"
    assert row.status == DigestSendStatus.SENT


@pytest.mark.asyncio
async def test_test_send_empty_plan_is_skipped_without_email() -> None:
    use_case, digests, sender = _build(plan=None)

    result = await use_case.execute(
        SendCoachDigestTestCommand(academy_id=ACADEMY_ID, target_user_id="coach-1", on_date=ON_DATE)
    )

    assert result.status == "skipped_empty"
    assert sender.sent == []
    assert next(iter(digests.by_id.values())).status == DigestSendStatus.SKIPPED_EMPTY


@pytest.mark.asyncio
async def test_test_send_unknown_target_raises() -> None:
    use_case, _digests, _sender = _build(_populated_plan())

    with pytest.raises(CoachDigestTargetNotFound):
        await use_case.execute(
            SendCoachDigestTestCommand(
                academy_id=ACADEMY_ID, target_user_id="ghost", on_date=ON_DATE
            )
        )


@pytest.mark.asyncio
async def test_test_send_no_email_marks_failed() -> None:
    use_case, digests, sender = _build(_populated_plan(), email=None)

    result = await use_case.execute(
        SendCoachDigestTestCommand(academy_id=ACADEMY_ID, target_user_id="coach-1", on_date=ON_DATE)
    )

    assert result.status == "failed"
    assert sender.sent == []
    assert next(iter(digests.by_id.values())).status == DigestSendStatus.FAILED
