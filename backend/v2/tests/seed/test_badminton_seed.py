"""Seed correctness tests for the Badminton Skill Pathway.

These tests are MANDATORY because of BWF Shuttle Time copyright risk.
They verify that:

* The seed loads on a fresh (empty) database.
* The seed is idempotent and does not duplicate records when run twice.
* A program, 6 levels, skills, and external references are created.
* `external_lesson_refs` contains ONLY reference metadata.
* No BWF lesson body text is stored anywhere in the seeded data.
* The reference model has no body / lesson_text / full_text / instructions
  (or any other content-bearing) fields.

The seed uses BWF Shuttle Time as an external *structural* reference only.
No copyrighted lesson content may ever enter source, seed data, or the DB.

pytest runs in ``asyncio_mode = "auto"`` so bare ``async def test_*`` works.
"""

from __future__ import annotations

from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    _LEVELS,
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.domain.models import (
    ExternalLessonReference,
    Level,
    Program,
    Skill,
    SkillCriterion,
)

ACADEMY_ID = "test-academy"

# Field names that would indicate copied lesson body / drill text. None of the
# curriculum models may declare any of these, and no seeded value may smuggle
# such content in.
FORBIDDEN_CONTENT_FIELDS = {
    "body",
    "lesson_text",
    "full_text",
    "text",
    "instructions",
    "drill",
    "drills",
    "drill_text",
    "content",
    "transcript",
    "steps",
}

# The ONLY fields an ExternalLessonReference is allowed to carry. Reference
# metadata + bookkeeping ids/dates — nothing that reproduces source content.
ALLOWED_REF_FIELDS = {
    "ref_id",
    "skill_id",
    "academy_id",
    "source",
    "source_title",
    "module_name",
    "lesson_range",
    "reference_title",
    "page_hint",
    "internal_note",
    "created_at",
    "created_by",
}


# ---------------------------------------------------------------------------
# In-memory fake repositories (no Mongo)
# ---------------------------------------------------------------------------


class FakeProgramRepository:
    def __init__(self) -> None:
        self.saved: list[Program] = []

    async def save(self, program: Program) -> None:
        self.saved.append(program)

    async def get(self, program_id: str) -> Program | None:
        return next((p for p in self.saved if p.program_id == program_id), None)

    async def list_active(self) -> list[Program]:
        return [p for p in self.saved if p.is_active]


class FakeLevelRepository:
    def __init__(self) -> None:
        self.saved: list[Level] = []

    async def save(self, level: Level) -> None:
        self.saved.append(level)

    async def update(self, level: Level) -> None:  # pragma: no cover - unused by seed
        self.saved.append(level)

    async def get(self, level_id: str) -> Level | None:
        return next((lv for lv in self.saved if lv.level_id == level_id), None)

    async def list_for_program(self, program_id: str) -> list[Level]:
        return [lv for lv in self.saved if lv.program_id == program_id]


class FakeSkillRepository:
    def __init__(self) -> None:
        self.saved: list[Skill] = []

    async def save(self, skill: Skill) -> None:
        self.saved.append(skill)

    async def update(self, skill: Skill) -> None:  # pragma: no cover - unused by seed
        self.saved.append(skill)

    async def get(self, skill_id: str) -> Skill | None:
        return next((s for s in self.saved if s.skill_id == skill_id), None)

    async def list_for_level(self, level_id: str) -> list[Skill]:
        return [s for s in self.saved if s.level_id == level_id]

    async def list_for_program(self, program_id: str) -> list[Skill]:
        return [s for s in self.saved if s.program_id == program_id]


class FakeCriterionRepository:
    def __init__(self) -> None:
        self.saved: list[SkillCriterion] = []

    async def save(self, criterion: SkillCriterion) -> None:
        self.saved.append(criterion)

    async def list_for_skill(self, skill_id: str) -> list[SkillCriterion]:
        return [c for c in self.saved if c.skill_id == skill_id]


class FakeExternalRefRepository:
    def __init__(self) -> None:
        self.saved: list[ExternalLessonReference] = []

    async def save(self, ref: ExternalLessonReference) -> None:
        self.saved.append(ref)

    async def list_for_skill(self, skill_id: str) -> list[ExternalLessonReference]:
        return [r for r in self.saved if r.skill_id == skill_id]


def _fresh_repos() -> dict[str, object]:
    return {
        "programs": FakeProgramRepository(),
        "levels": FakeLevelRepository(),
        "skills": FakeSkillRepository(),
        "criteria": FakeCriterionRepository(),
        "refs": FakeExternalRefRepository(),
    }


async def _run_seed(repos: dict[str, object], *, created_by: str = "admin") -> Program:
    return await seed_badminton_pathway(
        academy_id=ACADEMY_ID,
        programs=repos["programs"],  # type: ignore[arg-type]
        levels=repos["levels"],  # type: ignore[arg-type]
        skills=repos["skills"],  # type: ignore[arg-type]
        criteria=repos["criteria"],  # type: ignore[arg-type]
        refs=repos["refs"],  # type: ignore[arg-type]
        created_by=created_by,
    )


# Expected counts derived from the canonical seed data so the test stays in
# lockstep with the data without hard-coding magic numbers.
_EXPECTED_LEVELS = len(_LEVELS)
_EXPECTED_SKILLS = sum(len(level["skills"]) for level in _LEVELS)
_EXPECTED_CRITERIA = sum(len(skill["criteria"]) for level in _LEVELS for skill in level["skills"])
_EXPECTED_REFS = len(_LEVELS)  # one external reference per level


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_seed_loads_on_fresh_db() -> None:
    repos = _fresh_repos()
    program = await _run_seed(repos)

    assert isinstance(program, Program)
    assert program.sport == "badminton"
    assert program.name == "Badminton Skill Pathway"
    assert program.academy_id == ACADEMY_ID
    assert program.is_active is True
    assert len(repos["programs"].saved) == 1  # type: ignore[attr-defined]


async def test_seed_creates_program_levels_skills_and_refs() -> None:
    repos = _fresh_repos()
    program = await _run_seed(repos)

    levels = repos["levels"].saved  # type: ignore[attr-defined]
    skills = repos["skills"].saved  # type: ignore[attr-defined]
    criteria = repos["criteria"].saved  # type: ignore[attr-defined]
    refs = repos["refs"].saved  # type: ignore[attr-defined]

    assert len(levels) == _EXPECTED_LEVELS == 6
    assert len(skills) == _EXPECTED_SKILLS
    assert len(criteria) == _EXPECTED_CRITERIA
    # References ARE created — one per level (regression guard: they used to be
    # built but discarded with `_ = ref` and never persisted).
    assert len(refs) == _EXPECTED_REFS == 6

    # Levels are sequenced 1..6 and all belong to the seeded program.
    assert sorted(lv.sequence for lv in levels) == [1, 2, 3, 4, 5, 6]
    assert all(lv.program_id == program.program_id for lv in levels)

    # Every level has at least one skill, and every skill has criteria.
    for level in levels:
        level_skills = [s for s in skills if s.level_id == level.level_id]
        assert level_skills, f"level {level.sequence} has no skills"
        for skill in level_skills:
            assert [c for c in criteria if c.skill_id == skill.skill_id]

    # Each reference is anchored to a real seeded skill (not a dangling id).
    seeded_skill_ids = {s.skill_id for s in skills}
    assert all(ref.skill_id in seeded_skill_ids for ref in refs)


async def test_seed_is_idempotent_same_program() -> None:
    repos = _fresh_repos()
    first = await _run_seed(repos)
    second = await _run_seed(repos)

    # Second run returns the SAME program, not a new one.
    assert second.program_id == first.program_id


async def test_seed_run_twice_does_not_duplicate_records() -> None:
    repos = _fresh_repos()
    await _run_seed(repos)

    def _counts() -> dict[str, int]:
        return {
            "programs": len(repos["programs"].saved),  # type: ignore[attr-defined]
            "levels": len(repos["levels"].saved),  # type: ignore[attr-defined]
            "skills": len(repos["skills"].saved),  # type: ignore[attr-defined]
            "criteria": len(repos["criteria"].saved),  # type: ignore[attr-defined]
            "refs": len(repos["refs"].saved),  # type: ignore[attr-defined]
        }

    counts_after_first = _counts()
    await _run_seed(repos)
    counts_after_second = _counts()

    assert counts_after_first == counts_after_second
    assert counts_after_first["programs"] == 1


async def test_external_refs_contain_only_reference_metadata() -> None:
    repos = _fresh_repos()
    await _run_seed(repos)
    refs = repos["refs"].saved  # type: ignore[attr-defined]

    assert refs, "expected external references to be seeded"
    for ref in refs:
        dumped = ref.model_dump()
        # Exactly the allowed reference-metadata fields, nothing else.
        assert set(dumped.keys()) == ALLOWED_REF_FIELDS
        # Reference points at the academy's OWN structural mapping of BWF.
        assert ref.source == "BWF_SHUTTLE_TIME"
        assert ref.source_title == "BWF Shuttle Time"
        assert ref.module_name
        assert ref.lesson_range
        assert ref.reference_title
        # Internal note flags that content must not be reproduced.
        assert "reference only" in ref.internal_note.lower()


async def test_no_copyrighted_content_fields_on_any_model() -> None:
    """No curriculum model may declare a content-bearing field.

    Structural guard against ever storing BWF lesson body text: if such a
    field is added later, this test fails immediately.
    """
    for model in (Program, Level, Skill, SkillCriterion, ExternalLessonReference):
        field_names = set(model.model_fields.keys())
        leaked = field_names & FORBIDDEN_CONTENT_FIELDS
        assert not leaked, f"{model.__name__} declares forbidden content field(s): {leaked}"


async def test_no_bwf_lesson_body_text_in_seeded_values() -> None:
    """Seeded reference values must never carry verbatim lesson content.

    The reference only stores a short academy-authored title + page hint, so
    each text field stays well under any plausible copied-paragraph length and
    contains no newline-separated prose blocks.
    """
    repos = _fresh_repos()
    await _run_seed(repos)
    refs = repos["refs"].saved  # type: ignore[attr-defined]

    for ref in refs:
        for value in (ref.reference_title, ref.module_name, ref.lesson_range):
            assert "\n" not in value
            # Short metadata, not a copied paragraph.
            assert len(value) <= 120
        if ref.page_hint is not None:
            assert len(ref.page_hint) <= 40
