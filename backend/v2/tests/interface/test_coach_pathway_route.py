"""S68: GET /api/v2/coach/pathway, the academy's levels and lesson plans."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.v2.contexts.curriculum.domain.models import (
    FullPathway,
    LessonCard,
    LessonResourceLink,
    Level,
    PathwayLevel,
    Program,
    Skill,
    SkillWithCriteria,
)
from backend.v2.tests.interface.conftest import (
    _build_use_cases,
    _coach_claims,
    _make_app,
    _parent_claims,
)

T = datetime(2026, 11, 1, tzinfo=UTC)
COMMON = {"academy_id": "test-academy", "created_at": T, "updated_at": T, "created_by": "owner"}


def _level(level_id: str, seq: int, name: str, **extra) -> Level:
    return Level(level_id=level_id, program_id="p1", sequence=seq, name=name, **COMMON, **extra)


def _skill(skill_id: str, level_id: str, seq: int, name: str, **extra) -> SkillWithCriteria:
    skill = Skill(
        skill_id=skill_id,
        level_id=level_id,
        program_id="p1",
        sequence=seq,
        name=name,
        **COMMON,
        **extra,
    )
    return SkillWithCriteria(skill=skill, criteria=[], external_refs=[])


def _card(card_id: str, level_id: str, number: int, **extra) -> LessonCard:
    return LessonCard(
        card_id=card_id,
        program_id="p1",
        level_id=level_id,
        slug=card_id,
        lesson_number=number,
        title=f"Lesson {number}",
        goal_summary="Balanced, racket up",
        teaching_points=["Feet shoulder width"],
        equipment=["rackets"],
        safety_notes=["space between pairs"],
        activity_summary="mirror drill",
        module_name="Module 2",
        lesson_range="1-3",
        page_hint="p. 12",
        resource_links=[
            LessonResourceLink(kind="PDF_REFERENCE", title="Manual p. 12"),
            LessonResourceLink(kind="YOUTUBE", title="Drill", url="https://youtu.be/x"),
        ],
        **COMMON,
        **extra,
    )


class _Exec:
    def __init__(self, fn):
        self.execute = fn


def _curriculum():
    program = Program(program_id="p1", sport="badminton", name="Badminton Skill Pathway", **COMMON)
    pathway = FullPathway(
        program=program,
        levels=[
            PathwayLevel(
                level=_level("l2", 2, "Net and Movement"),
                skills=[_skill("s3", "l2", 1, "Net shot")],
            ),
            PathwayLevel(
                level=_level("l1", 1, "Grip and Control", description="Holding the racket."),
                skills=[
                    _skill("s2", "l1", 2, "V grip"),
                    _skill("s1", "l1", 1, "Thumb grip"),
                    _skill("sx", "l1", 3, "Old skill", is_active=False),
                ],
            ),
            PathwayLevel(level=_level("lx", 3, "Retired", is_active=False), skills=[]),
        ],
    )
    cards = [_card("c2", "l1", 2), _card("c1", "l1", 1), _card("cx", "l1", 3, is_active=False)]

    async def programs():
        return [program]

    async def full(program_id):
        assert program_id == "p1"
        return pathway

    async def lesson_cards(program_id):
        return cards

    return SimpleNamespace(
        list_programs=_Exec(programs),
        get_full_pathway=_Exec(full),
        list_lesson_cards=_Exec(lesson_cards),
    )


def _client(seed, claims=None):
    use_cases = replace(_build_use_cases(seed), curriculum=_curriculum())
    return TestClient(_make_app(claims or _coach_claims(), use_cases))


def test_pathway_lists_active_levels_skills_and_lessons_in_order(seed):
    r = _client(seed).get("/api/v2/coach/pathway")
    assert r.status_code == 200, r.text
    (program,) = r.json()["programs"]
    assert program["name"] == "Badminton Skill Pathway"
    assert [lv["name"] for lv in program["levels"]] == ["Grip and Control", "Net and Movement"]
    level1 = program["levels"][0]
    assert level1["description"] == "Holding the racket."
    assert [s["name"] for s in level1["skills"]] == ["Thumb grip", "V grip"]
    assert [c["card_id"] for c in level1["lessons"]] == ["c1", "c2"]
    lesson = level1["lessons"][0]
    assert lesson["teaching_points"] == ["Feet shoulder width"]
    assert lesson["video_url"] == "https://youtu.be/x"
    for citation in ("module_name", "lesson_range", "page_hint", "Manual p. 12", "source"):
        assert citation not in r.text
    assert program["levels"][1]["lessons"] == []


def test_pathway_without_curriculum_is_empty(seed):
    use_cases = replace(_build_use_cases(seed), curriculum=None)
    r = TestClient(_make_app(_coach_claims(), use_cases)).get("/api/v2/coach/pathway")
    assert r.status_code == 200 and r.json() == {"programs": []}


def test_parent_gets_404(seed):
    assert _client(seed, _parent_claims()).get("/api/v2/coach/pathway").status_code == 404
