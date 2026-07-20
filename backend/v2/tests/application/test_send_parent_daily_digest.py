"""SendParentDailyDigest use case behaviour (with in-memory fakes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_parent_daily_digest import (
    SendParentDailyDigest,
    SendParentDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    DigestSend,
    DigestSendStatus,
)

ACADEMY_ID = "acad-1"
DIGEST_DATE = date(2026, 7, 16)


@dataclass
class FakeParentDigestSendRepository:
    claimed: dict[tuple[str, str, str], DigestSend] = field(default_factory=dict)
    by_id: dict[str, DigestSend] = field(default_factory=dict)
    _counter: int = 0

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None:
        key = (academy_id, coach_id, digest_date)
        if key in self.claimed:
            return None
        self._counter += 1
        digest = DigestSend.queued(
            digest_id=f"pd-{self._counter:04d}",
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        self.claimed[key] = digest
        self.by_id[digest.digest_id] = digest
        return digest

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_sent(provider_message_id=provider_message_id, sent_at="now")

    async def mark_failed(self, digest_id: str, reason: str) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_failed(reason=reason)

    async def mark_skipped_empty(self, digest_id: str) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_skipped_empty()


@dataclass
class FakeParentResolver(AudienceResolver):
    parents: list[ResolvedRecipient] = field(default_factory=list)

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        assert audience.role == "parent"
        return list(self.parents)

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


@dataclass
class StubSendPort:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> SendOutcome:
        self.sent.append(
            {"email": recipient.email, "subject": subject, "body": body, "reply_to": reply_to}
        )
        return SendOutcome(
            ok=True, provider_message_id=f"stub-{len(self.sent)}", failed_reason=None
        )


@dataclass
class FakeProvider:
    view_by_parent: dict[str, ParentDigestView | None] = field(default_factory=dict)
    calls: list[tuple[str, date]] = field(default_factory=list)

    async def build_view(self, parent_id: str, on_date: date) -> ParentDigestView | None:
        self.calls.append((parent_id, on_date))
        return self.view_by_parent.get(parent_id)


def _view(*, on_portal: bool = True, reply_to: str | None = None) -> ParentDigestView:
    return ParentDigestView(
        parent_name="Parent",
        date_label="Thursday, July 16",
        program_name="Badminton",
        children=(
            ChildDigestView(
                child_name="Maithri",
                session_time="6:00 - 6:45 PM",
                session_label="Beginner @ YWCA",
                focus_skill="Thumb grip",
                focus_status="practicing",
            ),
        ),
        on_portal=on_portal,
        reply_to=reply_to,
    )


def _build(parents, views):
    digests = FakeParentDigestSendRepository()
    resolver = FakeParentResolver(parents=parents)
    sender = StubSendPort()
    provider = FakeProvider(view_by_parent=views)
    use_case = SendParentDailyDigest(
        digests=digests, resolver=resolver, sender=sender, provider=provider
    )
    return use_case, digests, sender, provider


@pytest.mark.asyncio
async def test_sends_one_digest_per_parent_with_a_session() -> None:
    use_case, digests, sender, _ = _build(
        parents=[ResolvedRecipient(user_id="p1", email="p1@example.test")],
        views={"p1": _view()},
    )

    result = await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.sent == 1
    assert result.skipped_empty == 0
    assert len(sender.sent) == 1
    assert sender.sent[0]["email"] == "p1@example.test"
    assert "Thumb grip" in sender.sent[0]["body"]
    assert digests.by_id["pd-0001"].status == DigestSendStatus.SENT


@pytest.mark.asyncio
async def test_parent_with_no_session_is_skipped_no_email() -> None:
    use_case, digests, sender, _ = _build(
        parents=[ResolvedRecipient(user_id="p1", email="p1@example.test")],
        views={"p1": None},
    )

    result = await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.skipped_empty == 1
    assert result.sent == 0
    assert sender.sent == []
    assert digests.by_id["pd-0001"].status == DigestSendStatus.SKIPPED_EMPTY


@pytest.mark.asyncio
async def test_second_run_same_date_sends_zero() -> None:
    use_case, _digests, sender, _ = _build(
        parents=[ResolvedRecipient(user_id="p1", email="p1@example.test")],
        views={"p1": _view()},
    )

    first = await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )
    second = await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert first.sent == 1
    assert second.sent == 0
    assert second.already_claimed == 1
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_parent_without_email_is_marked_failed() -> None:
    use_case, digests, sender, _ = _build(
        parents=[ResolvedRecipient(user_id="p1", email=None)],
        views={"p1": _view()},
    )

    result = await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.failed == 1
    assert result.sent == 0
    assert sender.sent == []
    assert digests.by_id["pd-0001"].status == DigestSendStatus.FAILED


@pytest.mark.asyncio
async def test_reply_to_is_forwarded_for_variant_b() -> None:
    use_case, _digests, sender, _ = _build(
        parents=[ResolvedRecipient(user_id="p1", email="p1@example.test")],
        views={"p1": _view(on_portal=False, reply_to="academy@example.test")},
    )

    await use_case.execute(
        SendParentDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert sender.sent[0]["reply_to"] == "academy@example.test"
