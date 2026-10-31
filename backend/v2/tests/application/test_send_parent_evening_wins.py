"""Parent evening win e-mail: copy and failure branches (fakes; the real-Mongo
path is covered by tests/contract/test_parent_evening_wins_real_mongo.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.contexts.communications.application.parent_wins import (
    ChildWins,
    FamilyWins,
    LevelUp,
    SkillWins,
    render_parent_wins,
)
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.communications.application.use_cases.send_parent_evening_wins import (
    SendParentEveningWins,
    SendParentEveningWinsCommand,
)

URL = "https://blno.example.test/parent/progress?child=s1"


def _child(name: str = "Aarav", **kw: Any) -> ChildWins:
    return ChildWins(first_name=name, progress_url=URL, **kw)


def _skills(names: tuple[str, ...], passed: int, total: int = 6) -> SkillWins:
    return SkillWins(
        level_name="Level 2", skill_names=names, passed_in_level=passed, total_in_level=total
    )


def test_skill_win_copy_counts_what_is_left() -> None:
    family = FamilyWins("p1", (_child(skill_wins=(_skills(("Forecourt movement",), 5),)),))
    subject, body = render_parent_wins(family, unsubscribe_url="https://x.test/u")
    assert subject == "Aarav mastered Forecourt movement today"
    assert "That&#x27;s 5 of 6 skills in Level 2, one to go." in body
    assert "https://x.test/u" in body


def test_several_skills_and_a_full_level_awaiting_its_level_up() -> None:
    family = FamilyWins("p1", (_child(skill_wins=(_skills(("Clear", "Drop"), 6),)),))
    subject, body = render_parent_wins(family)
    assert subject == "Aarav mastered 2 skills today"
    assert "Aarav mastered Clear and Drop today." in body
    assert "That&#x27;s every skill in Level 2 done." in body


def test_level_up_celebrates_and_links_the_certificate() -> None:
    family = FamilyWins("p1", (_child(level_ups=(LevelUp("Level 1", "Pathway"),)),))
    subject, body = render_parent_wins(family)
    assert subject == "Aarav finished Level 1 today!"
    assert "See the certificate" in body and URL.replace("&", "&amp;") in body


def test_names_are_escaped() -> None:
    family = FamilyWins("p1", (_child("<b>x</b>", skill_wins=(_skills(("<i>",), 1),)),))
    _, body = render_parent_wins(family)
    assert "<b>x</b>" not in body and "<i>" not in body


@dataclass
class _Claim:
    digest_id: str


@dataclass
class FakeClaims:
    claimed: set[str] = field(default_factory=set)
    failed: list[tuple[str, str, bool]] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)

    async def try_claim(self, academy_id: str, parent_id: str, day: str) -> _Claim | None:
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

    async def resolve_user_ids(self, user_ids: list[str]) -> list[ResolvedRecipient]:
        uid = user_ids[0]
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
    families: list[FamilyWins]
    window: tuple[datetime, datetime] | None = None

    async def families_with_wins(self, start: datetime, end: datetime) -> list[FamilyWins]:
        self.window = (start, end)
        return self.families


@pytest.mark.asyncio
async def test_provider_error_and_missing_email_branches() -> None:
    local_now = datetime(2026, 10, 30, 19, 0, tzinfo=ZoneInfo("America/Chicago"))
    families = [
        FamilyWins(p, (_child(skill_wins=(_skills(("Grip",), 1),)),)) for p in ("p1", "p2", "p3")
    ]
    claims = FakeClaims()
    provider = FakeProvider(families)
    use_case = SendParentEveningWins(
        claims=claims,  # type: ignore[arg-type]
        resolver=FakeResolver({"p1": "a@x.test", "p2": None}),  # type: ignore[arg-type]
        sender=FakeSender(SendOutcome(ok=False, provider_message_id=None, failed_reason="503")),  # type: ignore[arg-type]
        provider=provider,
    )
    result = await use_case.execute(SendParentEveningWinsCommand("acad", local_now))

    assert provider.window == (local_now.replace(hour=0), local_now)
    assert (result.families, result.sent, result.failed, result.retryable_failed) == (3, 0, 3, 1)
    # A provider outage stays retryable; a missing address does not.
    assert ("p1", "503", True) in claims.failed
    assert ("p2", "no email address", False) in claims.failed
    assert ("p3", "no email address", False) in claims.failed
