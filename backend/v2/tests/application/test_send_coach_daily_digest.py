"""SendCoachDailyDigest use case + renderer behaviour.

A stub send port is used so no real provider is ever contacted. The plan is a
synthetic stand-in for the coaching context's *Today's Teaching Plan* DTO —
the digest reads it purely by duck typing (ADR-0005: no cross-context import).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    COACH_GROUP_NOTE,
    GROUP_BLOCK_HEADING,
    WhatsAppGroupLink,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    DigestSend,
    DigestSendStatus,
)
from backend.v2.shared.comms.email_theme import EmailBrand

ACADEMY_ID = "acad-1"
DIGEST_DATE = date(2026, 6, 12)

# EN DASH (U+2013) — matches the lesson-card data shape ("Lessons 3-6", "p.16-30")
# built via chr() so there is no ambiguous dash literal in source (RUF001).
_EN = chr(0x2013)

CARD_YOUTUBE = "https://youtu.be/card-clip"
SKILL_YOUTUBE = "https://youtu.be/forehand-clear"
LEVEL_YOUTUBE = "https://youtu.be/level-1-playlist"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeDigestSendRepository:
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
        from datetime import UTC, datetime

        digest = DigestSend.queued(
            digest_id=f"dg-{self._counter:04d}",
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime(2026, 6, 12, tzinfo=UTC),
        )
        self.claimed[key] = digest
        self.by_id[digest.digest_id] = digest
        return digest

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_sent(provider_message_id=provider_message_id, sent_at="now")

    async def mark_failed(self, digest_id: str, reason: str, *, retryable: bool = True) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_failed(reason=reason, retryable=retryable)

    async def mark_skipped_empty(self, digest_id: str) -> None:
        d = self.by_id[digest_id]
        self.by_id[digest_id] = d.mark_skipped_empty()


@dataclass
class FakeCoachResolver(AudienceResolver):
    coaches: list[ResolvedRecipient] = field(default_factory=list)
    admins: list[ResolvedRecipient] = field(default_factory=list)

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        assert audience.role in ("coach", "admin")
        return list(self.coaches) if audience.role == "coach" else list(self.admins)

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
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome:
        self.sent.append(
            {
                "email": recipient.email,
                "subject": subject,
                "body": body,
                "cc": cc or [],
                "bcc": bcc or [],
                "category": category,
            }
        )
        return SendOutcome(
            ok=True, provider_message_id=f"stub-{len(self.sent)}", failed_reason=None
        )


@dataclass
class FakePlanProvider:
    plan_by_coach: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, date]] = field(default_factory=list)

    async def execute(self, coach_id: str, on_date: date) -> Any | None:
        self.calls.append((coach_id, on_date))
        return self.plan_by_coach.get(coach_id)


# ---------------------------------------------------------------------------
# Plan builders (synthetic DTO stand-ins)
# ---------------------------------------------------------------------------


def _populated_plan() -> Any:
    next_skill = SimpleNamespace(
        name="Forehand Clear",
        status="PRACTICING",
        youtube_links=[SimpleNamespace(title="Clear drill", url=SKILL_YOUTUBE)],
    )
    student = SimpleNamespace(student_name="Alice", focus="Forehand Clear", next_skill=next_skill)
    card = SimpleNamespace(
        title="Backhand Lift",
        source="BWF_SHUTTLE_TIME",
        module_name="Starter Lessons",
        lesson_range=f"Lessons 3{_EN}6",
        page_hint=f"16{_EN}30",
        resource_links=[
            SimpleNamespace(kind="YOUTUBE", title="Lesson clip", url=CARD_YOUTUBE),
            SimpleNamespace(kind="PDF_REFERENCE", title="Shuttle Time PDF", url=None),
        ],
    )
    group = SimpleNamespace(
        level_name="Level 1",
        youtube_links=[SimpleNamespace(title="Level playlist", url=LEVEL_YOUTUBE)],
        lesson_card=card,
        students=[student],
    )
    session = SimpleNamespace(
        title="Tuesday Juniors",
        location="Court A",
        start_at=None,
        end_at=None,
        groups=[group],
        unplaced=[SimpleNamespace(student_id="st-9", student_name="Bob")],
    )
    return SimpleNamespace(
        date="2026-06-12",
        program_name="Badminton",
        pathway_configured=True,
        sessions=[session],
    )


def _empty_plan() -> Any:
    return SimpleNamespace(
        date="2026-06-12", program_name="Badminton", pathway_configured=True, sessions=[]
    )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_renderer_includes_sessions_students_skills_youtube_and_pdf_citation() -> None:
    subject, body = render_coach_digest(_populated_plan())

    assert "2026-06-12" in subject
    assert "Tuesday Juniors" in body
    assert "Court A" in body
    assert "Level 1" in body
    assert "Backhand Lift" in body
    assert "Alice" in body
    assert "Forehand Clear" in body
    assert "practicing" in body
    assert "Bob" in body  # unplaced student listed
    # YouTube URLs verbatim, every scope.
    assert SKILL_YOUTUBE in body
    assert CARD_YOUTUBE in body
    assert LEVEL_YOUTUBE in body
    # PDF is citation text only — present as a reference, never as a link.
    assert f"Shuttle Time, Starter Lessons, Lessons 3{_EN}6, p.16{_EN}30" in body
    assert "Shuttle Time PDF" not in body  # PDF resource link title not rendered


def test_coach_digest_has_greeting_date_and_academy() -> None:
    plan = _populated_plan()
    _, body = render_coach_digest(plan, brand=EmailBrand(academy_name="BLNO Badminton"))
    assert "BLNO Badminton" in body
    assert "Good morning" in body
    assert "Friday, June 12" in body


def test_coach_digest_renders_groups_after_sessions() -> None:
    link = WhatsAppGroupLink(label="Tuesday Juniors", url="https://chat.whatsapp.com/AAA")
    _, body = render_coach_digest(
        _populated_plan(), whatsapp_groups=[link], playlist_url="https://yt/pl"
    )
    assert GROUP_BLOCK_HEADING in body and COACH_GROUP_NOTE in body
    assert (
        body.index("Not yet placed")
        < body.index(GROUP_BLOCK_HEADING)
        < body.index("Full video playlist")
    )


def test_coach_digest_without_playlist_has_no_empty_rule() -> None:
    _, body = render_coach_digest(_populated_plan())
    assert "Full video playlist" not in body
    # Only the shell footer and the unsubscribe footer draw a top rule on a
    # paragraph (student table rows have their own).
    assert body.count("margin:20px 0 0;border-top:1px solid") == 1  # unsubscribe
    assert body.count("margin:28px 0 0;border-top:1px solid") == 1  # shell footer
    assert "margin:16px 0 0;border-top:1px solid" not in body  # old empty rule


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


def _build(coaches, plans, admins=()):
    digests = FakeDigestSendRepository()
    resolver = FakeCoachResolver(coaches=coaches, admins=list(admins))
    sender = StubSendPort()
    provider = FakePlanProvider(plan_by_coach=plans)
    use_case = SendCoachDailyDigest(
        digests=digests, resolver=resolver, sender=sender, plan_provider=provider
    )
    return use_case, digests, sender, provider


@pytest.mark.asyncio
async def test_sends_personalized_digest_per_coach() -> None:
    use_case, digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _populated_plan()},
    )

    result = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.sent == 1
    assert result.skipped_empty == 0
    assert result.failed == 0
    assert len(sender.sent) == 1
    assert sender.sent[0]["email"] == "c1@example.test"
    assert "Forehand Clear" in sender.sent[0]["body"]
    assert digests.by_id["dg-0001"].status == DigestSendStatus.SENT


@pytest.mark.asyncio
async def test_empty_plan_is_skipped_with_no_email() -> None:
    use_case, digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _empty_plan()},
    )

    result = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.skipped_empty == 1
    assert result.sent == 0
    assert sender.sent == []  # zero EmailSendPort calls
    assert digests.by_id["dg-0001"].status == DigestSendStatus.SKIPPED_EMPTY


@pytest.mark.asyncio
async def test_second_run_same_date_sends_zero() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _populated_plan()},
    )

    first = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )
    second = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert first.sent == 1
    assert second.sent == 0
    assert second.already_claimed == 1
    # Only the first run reached the send port.
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_admin_is_bcc_d_on_every_coach_digest() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[
            ResolvedRecipient(user_id="coach-1", email="c1@example.test"),
            ResolvedRecipient(user_id="coach-2", email="c2@example.test"),
        ],
        plans={"coach-1": _populated_plan(), "coach-2": _populated_plan()},
        admins=[ResolvedRecipient(user_id="admin-1", email="admin@example.test")],
    )

    result = await use_case.execute(
        SendCoachDailyDigestCommand(
            academy_id=ACADEMY_ID, digest_date=DIGEST_DATE, admin_cc_enabled=True
        )
    )

    assert result.sent == 2
    # Admins are BCC'd (not CC'd) so no coach sees the admin addresses.
    assert [s["cc"] for s in sender.sent] == [[], []]
    assert [s["bcc"] for s in sender.sent] == [["admin@example.test"], ["admin@example.test"]]


@pytest.mark.asyncio
async def test_admin_copy_is_off_by_default() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _populated_plan()},
        admins=[ResolvedRecipient(user_id="admin-1", email="admin@example.test")],
    )

    await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert sender.sent[0]["cc"] == []
    assert sender.sent[0]["bcc"] == []


@pytest.mark.asyncio
async def test_admin_copy_excludes_the_coach_being_emailed() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="dual@example.test")],
        plans={"coach-1": _populated_plan()},
        admins=[ResolvedRecipient(user_id="coach-1", email="dual@example.test")],
    )

    await use_case.execute(
        SendCoachDailyDigestCommand(
            academy_id=ACADEMY_ID, digest_date=DIGEST_DATE, admin_cc_enabled=True
        )
    )

    assert sender.sent[0]["cc"] == []
    assert sender.sent[0]["bcc"] == []


@pytest.mark.asyncio
async def test_coach_without_email_is_marked_failed_not_sent() -> None:
    use_case, digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email=None)],
        plans={"coach-1": _populated_plan()},
    )

    result = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )

    assert result.failed == 1
    assert result.sent == 0
    assert sender.sent == []
    assert digests.by_id["dg-0001"].status == DigestSendStatus.FAILED


@pytest.mark.asyncio
async def test_group_links_and_brand_reach_the_email() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _populated_plan()},
    )
    use_case.group_links = SimpleNamespace(
        for_coach=AsyncMock(
            return_value=[
                WhatsAppGroupLink(label="Tuesday Juniors", url="https://chat.whatsapp.com/AAA")
            ]
        )
    )
    use_case.brands = SimpleNamespace(
        brand_for=AsyncMock(return_value=EmailBrand(academy_name="Brand Co"))
    )
    await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )
    body = sender.sent[0]["body"]
    assert GROUP_BLOCK_HEADING in body and "Brand Co" in body
    use_case.group_links.for_coach.assert_awaited_once_with("coach-1")


@pytest.mark.asyncio
async def test_group_link_provider_failure_does_not_block_send() -> None:
    use_case, _digests, sender, _ = _build(
        coaches=[ResolvedRecipient(user_id="coach-1", email="c1@example.test")],
        plans={"coach-1": _populated_plan()},
    )
    use_case.group_links = SimpleNamespace(for_coach=AsyncMock(side_effect=RuntimeError("x")))
    result = await use_case.execute(
        SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=DIGEST_DATE)
    )
    assert result.sent == 1
    assert GROUP_BLOCK_HEADING not in sender.sent[0]["body"]
