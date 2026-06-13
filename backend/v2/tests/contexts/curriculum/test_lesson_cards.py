"""Unit tests for lesson-card read use cases (GetLessonCardForSkill, ListLessonCards)."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.curriculum.application.use_cases.manage_lesson_cards import (
    GetLessonCardForSkill,
    ListLessonCards,
)
from backend.v2.contexts.curriculum.domain.models import LessonCard

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _card(
    *,
    slug: str,
    skill_ids: list[str],
    display_order: int,
    lesson_number: int,
    program_id: str = "prog-1",
) -> LessonCard:
    return LessonCard(
        card_id=f"card-{slug}",
        academy_id="acad-1",
        program_id=program_id,
        level_id="lvl-1",
        skill_ids=skill_ids,
        slug=slug,
        lesson_number=lesson_number,
        title=slug,
        created_at=_NOW,
        updated_at=_NOW,
        created_by="tester",
        display_order=display_order,
    )


class FakeLessonCardRepository:
    def __init__(self, cards: list[LessonCard]) -> None:
        self._cards = cards

    async def get_by_slug(self, program_id: str, slug: str) -> LessonCard | None:
        return next((c for c in self._cards if c.slug == slug), None)

    async def save(self, card: LessonCard) -> None:  # pragma: no cover - unused here
        self._cards.append(card)

    async def replace(self, card: LessonCard) -> None:  # pragma: no cover - unused here
        self._cards = [card if c.slug == card.slug else c for c in self._cards]

    async def list_for_program(self, program_id: str) -> list[LessonCard]:
        return [c for c in self._cards if c.program_id == program_id]

    async def list_for_skill(self, skill_id: str) -> list[LessonCard]:
        return [c for c in self._cards if skill_id in c.skill_ids]


async def test_get_card_for_skill_resolves_matching_card() -> None:
    repo = FakeLessonCardRepository(
        [_card(slug="l1", skill_ids=["sk-1"], display_order=1, lesson_number=1)]
    )
    card = await GetLessonCardForSkill(cards=repo).execute("sk-1")  # type: ignore[arg-type]
    assert card is not None
    assert card.slug == "l1"


async def test_get_card_for_skill_returns_none_when_no_card() -> None:
    repo = FakeLessonCardRepository(
        [_card(slug="l1", skill_ids=["sk-1"], display_order=1, lesson_number=1)]
    )
    card = await GetLessonCardForSkill(cards=repo).execute("sk-missing")  # type: ignore[arg-type]
    assert card is None


async def test_get_card_for_skill_prefers_lowest_display_order() -> None:
    repo = FakeLessonCardRepository(
        [
            _card(slug="later", skill_ids=["sk-1"], display_order=5, lesson_number=5),
            _card(slug="earlier", skill_ids=["sk-1"], display_order=2, lesson_number=9),
        ]
    )
    card = await GetLessonCardForSkill(cards=repo).execute("sk-1")  # type: ignore[arg-type]
    assert card is not None
    assert card.slug == "earlier"


async def test_get_card_for_skill_breaks_ties_on_lesson_number() -> None:
    repo = FakeLessonCardRepository(
        [
            _card(slug="b", skill_ids=["sk-1"], display_order=3, lesson_number=8),
            _card(slug="a", skill_ids=["sk-1"], display_order=3, lesson_number=4),
        ]
    )
    card = await GetLessonCardForSkill(cards=repo).execute("sk-1")  # type: ignore[arg-type]
    assert card is not None
    assert card.slug == "a"


async def test_list_lesson_cards_filters_by_program() -> None:
    repo = FakeLessonCardRepository(
        [
            _card(
                slug="p1",
                skill_ids=["sk-1"],
                display_order=1,
                lesson_number=1,
                program_id="prog-1",
            ),
            _card(
                slug="p2",
                skill_ids=["sk-2"],
                display_order=1,
                lesson_number=1,
                program_id="prog-2",
            ),
        ]
    )
    cards = await ListLessonCards(cards=repo).execute("prog-1")  # type: ignore[arg-type]
    assert [c.slug for c in cards] == ["p1"]
