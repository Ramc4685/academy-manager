"""Seed correctness tests for badminton lesson cards + curriculum video refs.

These tests are MANDATORY because of BWF Shuttle Time copyright risk and
because cards reference the pathway by sequence (ids are per-academy). They
verify that:

* The content JSON parses and covers all 22 lessons.
* Every card resolves its level/skill sequences against the seeded pathway.
* Level/skill video refs resolve and upsert.
* Seeding is idempotent (a reseed is a no-op) and a content-hash change
  updates the card in place without changing its id.
* PDF references stay pointer-only (citation chip, url=None).
* Seeding without a pathway raises a clear error.

pytest runs in ``asyncio_mode = "auto"`` so bare ``async def test_*`` works.
"""

from __future__ import annotations

import json

import pytest

from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_lesson_cards import (
    LessonCardSeedError,
    PathwayNotSeededError,
    load_content,
    seed_lesson_cards,
)
from backend.v2.contexts.curriculum.domain.models import CurriculumVideoRef, LessonCard
from backend.v2.tests.seed.test_badminton_seed import (
    FakeCriterionRepository,
    FakeExternalRefRepository,
    FakeLevelRepository,
    FakeProgramRepository,
    FakeSkillRepository,
)

ACADEMY_ID = "test-academy"

# The only fields a CurriculumVideoRef may carry — pointer metadata, no
# transcript / lesson text.
ALLOWED_VIDEO_REF_FIELDS = {
    "ref_id",
    "academy_id",
    "program_id",
    "scope",
    "level_id",
    "skill_id",
    "title",
    "url",
    "display_order",
    "content_hash",
    "is_active",
    "created_at",
    "created_by",
}


class FakeLessonCardRepository:
    def __init__(self) -> None:
        self.saved: dict[str, LessonCard] = {}

    async def get_by_slug(self, slug: str) -> LessonCard | None:
        return self.saved.get(slug)

    async def save(self, card: LessonCard) -> None:
        self.saved[card.slug] = card

    async def replace(self, card: LessonCard) -> None:
        self.saved[card.slug] = card

    async def list_for_program(self, program_id: str) -> list[LessonCard]:
        return [c for c in self.saved.values() if c.program_id == program_id]

    async def list_for_skill(self, skill_id: str) -> list[LessonCard]:
        return [c for c in self.saved.values() if skill_id in c.skill_ids]


class FakeVideoRefRepository:
    def __init__(self) -> None:
        self.saved: list[CurriculumVideoRef] = []

    @staticmethod
    def _key(scope: str, level_id: str, skill_id: str | None, url: str) -> tuple:
        return (scope, level_id, skill_id, url)

    async def get_by_identity(
        self, *, scope: str, level_id: str, skill_id: str | None, url: str
    ) -> CurriculumVideoRef | None:
        want = self._key(scope, level_id, skill_id, url)
        for ref in self.saved:
            if self._key(ref.scope, ref.level_id, ref.skill_id, ref.url) == want:
                return ref
        return None

    async def save(self, ref: CurriculumVideoRef) -> None:
        self.saved.append(ref)

    async def replace(self, ref: CurriculumVideoRef) -> None:
        want = self._key(ref.scope, ref.level_id, ref.skill_id, ref.url)
        for i, existing in enumerate(self.saved):
            key = self._key(existing.scope, existing.level_id, existing.skill_id, existing.url)
            if key == want:
                self.saved[i] = ref
                return
        self.saved.append(ref)

    async def list_for_level(self, level_id: str) -> list[CurriculumVideoRef]:
        return [r for r in self.saved if r.scope == "LEVEL" and r.level_id == level_id]

    async def list_for_skills(self, skill_ids: list[str]) -> list[CurriculumVideoRef]:
        return [r for r in self.saved if r.scope == "SKILL" and r.skill_id in skill_ids]


async def _seed_pathway() -> tuple[FakeProgramRepository, FakeLevelRepository, FakeSkillRepository]:
    programs = FakeProgramRepository()
    levels = FakeLevelRepository()
    skills = FakeSkillRepository()
    criteria = FakeCriterionRepository()
    refs = FakeExternalRefRepository()
    await seed_badminton_pathway(
        academy_id=ACADEMY_ID,
        programs=programs,  # type: ignore[arg-type]
        levels=levels,  # type: ignore[arg-type]
        skills=skills,  # type: ignore[arg-type]
        criteria=criteria,  # type: ignore[arg-type]
        refs=refs,  # type: ignore[arg-type]
        created_by="admin",
    )
    return programs, levels, skills


async def _seed_cards(
    programs: FakeProgramRepository,
    levels: FakeLevelRepository,
    skills: FakeSkillRepository,
    *,
    content_path=None,
):
    cards = FakeLessonCardRepository()
    videos = FakeVideoRefRepository()
    result = await seed_lesson_cards(
        academy_id=ACADEMY_ID,
        programs=programs,  # type: ignore[arg-type]
        levels=levels,  # type: ignore[arg-type]
        skills=skills,  # type: ignore[arg-type]
        cards=cards,  # type: ignore[arg-type]
        video_refs=videos,  # type: ignore[arg-type]
        created_by="admin",
        content_path=content_path,
    )
    return result, cards, videos


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_content_json_parses_and_covers_22_lessons() -> None:
    content = load_content()
    cards = content["cards"]
    assert len(cards) == 22
    assert sorted(c["lesson_number"] for c in cards) == list(range(1, 23))
    slugs = [c["slug"] for c in cards]
    assert len(set(slugs)) == 22
    assert "ORIGINAL" in content["_license_note"]


async def test_seed_creates_all_cards_and_level_videos() -> None:
    programs, levels, skills = await _seed_pathway()
    result, cards, videos = await _seed_cards(programs, levels, skills)

    assert result.cards_created == 22
    assert result.cards_updated == 0
    assert result.cards_unchanged == 0
    assert result.video_refs_created == 107
    assert any(r.scope == "LEVEL" for r in videos.saved)
    assert any(r.scope == "SKILL" for r in videos.saved)
    assert len(cards.saved) == 22


async def test_every_card_resolves_to_real_pathway_ids() -> None:
    programs, levels, skills = await _seed_pathway()
    _result, cards, _videos = await _seed_cards(programs, levels, skills)

    level_ids = {lv.level_id for lv in levels.saved}
    skill_ids = {s.skill_id for s in skills.saved}
    for card in cards.saved.values():
        assert card.level_id in level_ids
        assert card.skill_ids, f"{card.slug} resolved no skills"
        assert all(sid in skill_ids for sid in card.skill_ids)


async def test_reseed_is_a_noop() -> None:
    programs, levels, skills = await _seed_pathway()
    cards = FakeLessonCardRepository()
    videos = FakeVideoRefRepository()

    async def _run():
        return await seed_lesson_cards(
            academy_id=ACADEMY_ID,
            programs=programs,  # type: ignore[arg-type]
            levels=levels,  # type: ignore[arg-type]
            skills=skills,  # type: ignore[arg-type]
            cards=cards,  # type: ignore[arg-type]
            video_refs=videos,  # type: ignore[arg-type]
            created_by="admin",
        )

    await _run()
    second = await _run()
    assert second.cards_created == 0
    assert second.cards_updated == 0
    assert second.cards_unchanged == 22
    assert second.video_refs_created == 0
    assert second.video_refs_unchanged == 107
    assert len(cards.saved) == 22
    assert len(videos.saved) == 107


async def test_content_hash_change_updates_in_place_keeping_id() -> None:
    programs, levels, skills = await _seed_pathway()
    cards = FakeLessonCardRepository()
    videos = FakeVideoRefRepository()
    common = dict(
        academy_id=ACADEMY_ID,
        programs=programs,
        levels=levels,
        skills=skills,
        cards=cards,
        video_refs=videos,
        created_by="admin",
    )
    await seed_lesson_cards(**common)  # type: ignore[arg-type]

    target = cards.saved["bwf-st-lesson-01"]
    original_id = target.card_id
    cards.saved["bwf-st-lesson-01"] = target.model_copy(update={"content_hash": "stale"})

    result = await seed_lesson_cards(**common)  # type: ignore[arg-type]
    assert result.cards_updated == 1
    assert result.cards_unchanged == 21
    assert cards.saved["bwf-st-lesson-01"].card_id == original_id


async def test_pdf_references_stay_pointer_only() -> None:
    programs, levels, skills = await _seed_pathway()
    _result, cards, _videos = await _seed_cards(programs, levels, skills)

    for card in cards.saved.values():
        pdf_links = [link for link in card.resource_links if link.kind == "PDF_REFERENCE"]
        assert pdf_links, f"{card.slug} missing PDF citation chip"
        for link in pdf_links:
            assert link.url is None


async def test_video_refs_carry_only_pointer_metadata() -> None:
    programs, levels, skills = await _seed_pathway()
    _result, _cards, videos = await _seed_cards(programs, levels, skills)

    assert videos.saved
    for ref in videos.saved:
        assert set(ref.model_dump().keys()) == ALLOWED_VIDEO_REF_FIELDS
        assert ref.url.startswith("https://")


async def test_seed_requires_pathway_first() -> None:
    programs = FakeProgramRepository()
    levels = FakeLevelRepository()
    skills = FakeSkillRepository()
    with pytest.raises(PathwayNotSeededError):
        await _seed_cards(programs, levels, skills)


async def test_unresolvable_sequence_raises(tmp_path) -> None:
    programs, levels, skills = await _seed_pathway()
    bad = {
        "source": "BWF_SHUTTLE_TIME",
        "cards": [
            {
                "slug": "bad-card",
                "lesson_number": 1,
                "level_sequence": 99,
                "skill_sequences": [1],
                "title": "Bad",
                "resource_links": [],
            }
        ],
        "level_videos": [],
        "skill_videos": [],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(LessonCardSeedError):
        await _seed_cards(programs, levels, skills, content_path=path)
