"""Parent monthly report card: copy, month window and failure branches (fakes;
the real-Mongo path is covered by
tests/contract/test_parent_report_cards_real_mongo.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.communications.application.parent_report_card import (
    ChildReportCard,
    FamilyReportCard,
    Focus,
    render_parent_report_card,
)
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.application.use_cases.send_parent_report_cards import (
    SendParentReportCards,
    SendParentReportCardsCommand,
    month_names,
    report_month,
)

URL = "https://blno.example.test/parent/progress?child=s1"
CHICAGO = ZoneInfo("America/Chicago")


def _child(name: str = "Aarav", **kw: Any) -> ChildReportCard:
    base: dict[str, Any] = {
        "new_skills": 4,
        "classes_attended": 7,
        "classes_marked": 8,
        "level_badge": "L2",
        "level_name": "Level 2",
    }
    return ChildReportCard(first_name=name, progress_url=URL, **(base | kw))


def _family(*children: ChildReportCard, parent: str = "p1") -> FamilyReportCard:
    return FamilyReportCard(parent, "October", "November", children)


def test_card_shows_the_design_numbers_and_focus_video() -> None:
    focus = Focus("Backhand net shot", "https://video.test/bh")
    subject, body = render_parent_report_card(
        _family(_child(focus=focus)), unsubscribe_url="https://x.test/u"
    )
    assert subject == "October for Aarav"
    for text in ("October for Aarav", "4", "new skills", "7/8", "L2", "Level 2"):
        assert text in body
    assert "Focus for November: Backhand net shot." in body
    assert 'href="https://video.test/bh"' in body
    assert "https://x.test/u" in body


def test_family_card_covers_every_child_and_skips_missing_parts() -> None:
    subject, body = render_parent_report_card(
        _family(_child(), _child("Mira", new_skills=1, level_badge=None, level_name=None))
    )
    assert subject == "October for Aarav and Mira"
    assert "October for Mira" in body and "1</div>" in body and "new skill<" in body
    assert "Focus for" not in body  # no focus for either child


def test_non_web_video_url_is_not_linked_and_names_are_escaped() -> None:
    focus = Focus("<i>Drop</i>", "javascript:alert(1)")
    _, body = render_parent_report_card(_family(_child("<b>x</b>", focus=focus)))
    assert "javascript:" not in body
    assert "<b>x</b>" not in body and "<i>Drop</i>" not in body


def test_report_month_is_the_previous_calendar_month_in_local_time() -> None:
    start, end = report_month(datetime(2026, 11, 1, 9, 0, tzinfo=CHICAGO))
    assert (start, end) == (
        datetime(2026, 10, 1, tzinfo=CHICAGO),
        datetime(2026, 11, 1, tzinfo=CHICAGO),
    )
    start, _ = report_month(datetime(2027, 1, 1, 9, 0, tzinfo=CHICAGO))
    assert start == datetime(2026, 12, 1, tzinfo=CHICAGO)
    assert month_names(start) == ("December", "January")


@dataclass
class _Claim:
    digest_id: str


@dataclass
class FakeClaims:
    claimed: set[str] = field(default_factory=set)
    keys: list[str] = field(default_factory=list)
    failed: list[tuple[str, str, bool]] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)

    async def try_claim(self, academy_id: str, parent_id: str, key: str) -> _Claim | None:
        self.keys.append(key)
        if parent_id in self.claimed:
            return None
        self.claimed.add(parent_id)
        return _Claim(parent_id)

    async def mark_sent(self, academy_id: str, digest_id: str, pmid: str | None) -> None:
        self.sent.append(digest_id)

    async def mark_failed(
        self, academy_id: str, digest_id: str, reason: str, *, retryable: bool = True
    ) -> None:
        self.failed.append((digest_id, reason, retryable))


@dataclass
class FakeResolver:
    emails: dict[str, str | None]

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        uid = audience.user_ids[0]
        return (
            [ResolvedRecipient(user_id=uid, email=self.emails[uid])] if uid in self.emails else []
        )


@dataclass
class FakeSender:
    outcome: SendOutcome

    async def send(self, **kw: Any) -> SendOutcome:
        return self.outcome


@dataclass
class FakeProvider:
    families: list[FamilyReportCard]
    window: tuple[datetime, datetime] | None = None

    async def families_for_month(self, start: datetime, end: datetime) -> list[FamilyReportCard]:
        self.window = (start, end)
        return self.families


def _use_case(claims: FakeClaims, provider: FakeProvider, outcome: SendOutcome) -> Any:
    return SendParentReportCards(
        claims=claims,  # type: ignore[arg-type]
        resolver=FakeResolver({"p1": "a@x.test", "p2": None}),  # type: ignore[arg-type]
        sender=FakeSender(outcome),  # type: ignore[arg-type]
        provider=provider,
    )


@pytest.mark.asyncio
async def test_only_the_first_of_the_month_sends() -> None:
    provider = FakeProvider([_family()])
    use_case = _use_case(
        FakeClaims(), provider, SendOutcome(ok=True, provider_message_id="m", failed_reason=None)
    )
    result = await use_case.execute(
        SendParentReportCardsCommand("acad", datetime(2026, 11, 2, 9, 0, tzinfo=CHICAGO))
    )
    assert result.families == 0 and provider.window is None


@pytest.mark.asyncio
async def test_claims_per_month_and_failure_branches() -> None:
    local_now = datetime(2026, 11, 1, 9, 0, tzinfo=CHICAGO)
    claims = FakeClaims()
    provider = FakeProvider([_family(_child(), parent=p) for p in ("p1", "p2", "p3")])
    use_case = _use_case(
        claims, provider, SendOutcome(ok=False, provider_message_id=None, failed_reason="503")
    )
    result = await use_case.execute(SendParentReportCardsCommand("acad", local_now))

    assert provider.window == report_month(local_now)
    assert set(claims.keys) == {"2026-10"}
    assert (result.families, result.sent, result.failed) == (3, 0, 3)
    # A provider outage stays retryable; a missing address does not.
    assert ("p1", "503", True) in claims.failed
    assert ("p2", "no email address", False) in claims.failed
    assert ("p3", "no email address", False) in claims.failed
