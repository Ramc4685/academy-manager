"""Interface tests for admin program/pathway routes.

Tests a standalone mini FastAPI app that wires fake in-memory repos directly
to the curriculum use cases. No Mongo, no real auth.

Routes covered:
- POST  /api/v2/admin/programs             → 201, returns program
- GET   /api/v2/admin/programs             → 200, list
- POST  /api/v2/admin/programs/{id}/seed-badminton  → 200, idempotent
- GET   /api/v2/admin/programs/{id}/pathway → 200
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.domain.models import (
    ExternalLessonReference,
    FullPathway,
    LessonCard,
    Level,
    PathwayLevel,
    Program,
    Skill,
    SkillCriterion,
    SkillWithCriteria,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.pathway_routes import router as pathway_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.ids import new_ulid

# ---------------------------------------------------------------------------
# Fake in-memory repositories
# ---------------------------------------------------------------------------


class FakeProgramRepository:
    def __init__(self) -> None:
        self._store: dict[str, Program] = {}

    async def save(self, program: Program) -> None:
        self._store[program.program_id] = program

    async def get(self, program_id: str) -> Program | None:
        return self._store.get(program_id)

    async def list_active(self) -> list[Program]:
        return [p for p in self._store.values() if p.is_active]


class FakeLevelRepository:
    def __init__(self) -> None:
        self._store: dict[str, Level] = {}

    async def save(self, level: Level) -> None:
        self._store[level.level_id] = level

    async def update(self, level: Level) -> None:
        self._store[level.level_id] = level

    async def get(self, level_id: str) -> Level | None:
        return self._store.get(level_id)

    async def list_for_program(self, program_id: str) -> list[Level]:
        return sorted(
            [lv for lv in self._store.values() if lv.program_id == program_id],
            key=lambda lv: lv.sequence,
        )


class FakeSkillRepository:
    def __init__(self) -> None:
        self._store: dict[str, Skill] = {}

    async def save(self, skill: Skill) -> None:
        self._store[skill.skill_id] = skill

    async def update(self, skill: Skill) -> None:
        self._store[skill.skill_id] = skill

    async def get(self, skill_id: str) -> Skill | None:
        return self._store.get(skill_id)

    async def list_for_level(self, level_id: str) -> list[Skill]:
        return sorted(
            [s for s in self._store.values() if s.level_id == level_id],
            key=lambda s: s.sequence,
        )

    async def list_for_program(self, program_id: str) -> list[Skill]:
        return [s for s in self._store.values() if s.program_id == program_id]


class FakeCriterionRepository:
    def __init__(self) -> None:
        self._store: dict[str, SkillCriterion] = {}

    async def save(self, criterion: SkillCriterion) -> None:
        self._store[criterion.criterion_id] = criterion

    async def list_for_skill(self, skill_id: str) -> list[SkillCriterion]:
        return [c for c in self._store.values() if c.skill_id == skill_id]


class FakeExternalRefRepository:
    def __init__(self) -> None:
        self._store: dict[str, ExternalLessonReference] = {}

    async def save(self, ref: ExternalLessonReference) -> None:
        self._store[ref.ref_id] = ref

    async def list_for_skill(self, skill_id: str) -> list[ExternalLessonReference]:
        return [r for r in self._store.values() if r.skill_id == skill_id]


class FakePathwayQuery:
    def __init__(
        self,
        programs: FakeProgramRepository,
        levels: FakeLevelRepository,
        skills: FakeSkillRepository,
        criteria: FakeCriterionRepository,
    ) -> None:
        self._programs = programs
        self._levels = levels
        self._skills = skills
        self._criteria = criteria

    async def get_full_pathway(self, program_id: str) -> FullPathway | None:
        program = await self._programs.get(program_id)
        if program is None:
            return None
        levels_list = await self._levels.list_for_program(program_id)
        levels_with_skills: list[Any] = []
        for lv in levels_list:
            skills_list = await self._skills.list_for_level(lv.level_id)
            skills_with_criteria: list[SkillWithCriteria] = []
            for sk in skills_list:
                crits = await self._criteria.list_for_skill(sk.skill_id)
                skills_with_criteria.append(
                    SkillWithCriteria(skill=sk, criteria=crits, external_refs=[])
                )
            levels_with_skills.append(PathwayLevel(level=lv, skills=skills_with_criteria))
        return FullPathway(program=program, levels=levels_with_skills)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@dataclass
class _PathwayState:
    programs: FakeProgramRepository
    levels: FakeLevelRepository
    skills: FakeSkillRepository
    criteria: FakeCriterionRepository
    refs: FakeExternalRefRepository
    pathway_query: FakePathwayQuery


def _build_app(*, academy_id: str = "test-academy") -> FastAPI:
    progs = FakeProgramRepository()
    levs = FakeLevelRepository()
    skils = FakeSkillRepository()
    crits = FakeCriterionRepository()
    refs = FakeExternalRefRepository()
    pq = FakePathwayQuery(progs, levs, skils, crits)

    app = FastAPI()
    app.state.pathway = _PathwayState(
        programs=progs,
        levels=levs,
        skills=skils,
        criteria=crits,
        refs=refs,
        pathway_query=pq,
    )
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id=academy_id,
        roles=("admin",),
    )

    @app.post("/api/v2/admin/programs", status_code=201)
    async def create_program(body: dict, request: Request) -> dict:
        state: _PathwayState = request.app.state.pathway
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        program = Program(
            program_id=str(new_ulid()),
            academy_id=academy_id,
            sport=body.get("sport", "badminton"),
            name=body.get("name", "Program"),
            description=body.get("description", ""),
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by="admin-1",
        )
        await state.programs.save(program)
        return program.model_dump(mode="json")

    @app.get("/api/v2/admin/programs")
    async def list_programs(request: Request) -> dict:
        state: _PathwayState = request.app.state.pathway
        progs = await state.programs.list_active()
        return {"programs": [p.model_dump(mode="json") for p in progs]}

    @app.post("/api/v2/admin/programs/{program_id}/seed-badminton")
    async def seed_badminton(program_id: str, request: Request) -> dict:
        state: _PathwayState = request.app.state.pathway
        program = await seed_badminton_pathway(
            academy_id=academy_id,
            programs=state.programs,
            levels=state.levels,
            skills=state.skills,
            criteria=state.criteria,
            refs=state.refs,
            created_by="admin-1",
        )
        return {"program_id": program.program_id, "name": program.name}

    @app.get("/api/v2/admin/programs/{program_id}/pathway")
    async def get_pathway(program_id: str, request: Request) -> dict:
        state: _PathwayState = request.app.state.pathway
        result = await state.pathway_query.get_full_pathway(program_id)
        if result is None:
            raise HTTPException(status_code=404, detail="program not found")
        return result.model_dump(mode="json")

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_program_returns_201():
    app = _build_app()
    client = TestClient(app)
    r = client.post(
        "/api/v2/admin/programs",
        json={"sport": "badminton", "name": "Test Pathway", "description": "desc"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sport"] == "badminton"
    assert body["name"] == "Test Pathway"
    assert "program_id" in body


def test_list_programs_returns_200():
    app = _build_app()
    client = TestClient(app)
    # seed one first
    client.post(
        "/api/v2/admin/programs",
        json={"sport": "badminton", "name": "Badminton Pathway"},
    )
    r = client.get("/api/v2/admin/programs")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "programs" in body
    assert len(body["programs"]) == 1


def test_seed_badminton_returns_200():
    app = _build_app()
    client = TestClient(app)
    r = client.post("/api/v2/admin/programs/any-id/seed-badminton")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Badminton Skill Pathway"
    assert "program_id" in body


def test_seed_badminton_is_idempotent():
    app = _build_app()
    client = TestClient(app)
    r1 = client.post("/api/v2/admin/programs/any-id/seed-badminton")
    r2 = client.post("/api/v2/admin/programs/any-id/seed-badminton")
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    # same program_id returned both times
    assert r1.json()["program_id"] == r2.json()["program_id"]


def test_get_pathway_returns_200():
    app = _build_app()
    client = TestClient(app)
    seed_r = client.post("/api/v2/admin/programs/any-id/seed-badminton")
    program_id = seed_r.json()["program_id"]

    r = client.get(f"/api/v2/admin/programs/{program_id}/pathway")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "program" in body
    assert "levels" in body
    assert len(body["levels"]) == 6  # badminton pathway has 6 levels


def test_get_pathway_unknown_program_returns_404():
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/v2/admin/programs/does-not-exist/pathway")
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# GET /programs/{id}/lesson-cards — mounts the REAL router and overrides the
# admin use-case dependency so the route's own logic (summary shaping + the
# 503 guard) is exercised, not a re-implementation.
# ---------------------------------------------------------------------------


def _make_lesson_card(*, lesson_number: int = 1, title: str = "Card") -> LessonCard:
    now = datetime.now(UTC)
    return LessonCard(
        card_id=str(new_ulid()),
        academy_id="test-academy",
        program_id="prog-1",
        level_id="level-1",
        skill_ids=["skill-a", "skill-b"],
        slug=f"lesson-{lesson_number}",
        lesson_number=lesson_number,
        title=title,
        module_name="Module A",
        lesson_range="1-3",
        display_order=lesson_number,
        created_at=now,
        updated_at=now,
        created_by="admin-1",
    )


def _build_real_router_app(*, curriculum: Any) -> FastAPI:
    """Mount the real pathway router with a stub AdminUseCases.

    Only ``curriculum`` is wired; the lesson-card route is the only thing
    under test. ``curriculum=None`` exercises the 503 guard.
    """
    app = FastAPI()
    app.include_router(pathway_router, prefix="/api/v2/admin")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1",
        email="admin@example.com",
        academy_id="test-academy",
        roles=("admin",),
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(
        curriculum=curriculum
    )
    return app


def test_list_lesson_cards_returns_summary_shape():
    cards = [
        _make_lesson_card(lesson_number=1, title="Grip"),
        _make_lesson_card(lesson_number=2, title="Serve"),
    ]
    curriculum = SimpleNamespace(
        list_lesson_cards=SimpleNamespace(execute=AsyncMock(return_value=cards))
    )
    app = _build_real_router_app(curriculum=curriculum)
    client = TestClient(app)

    r = client.get("/api/v2/admin/programs/prog-1/lesson-cards")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert len(body["cards"]) == 2
    first = body["cards"][0]
    assert set(first.keys()) == {
        "card_id",
        "slug",
        "lesson_number",
        "title",
        "module_name",
        "lesson_range",
        "skill_ids",
    }
    assert first["title"] == "Grip"
    assert first["skill_ids"] == ["skill-a", "skill-b"]
    # use case called with the path program_id
    curriculum.list_lesson_cards.execute.assert_awaited_once_with("prog-1")


def test_list_lesson_cards_empty_reports_zero_count():
    curriculum = SimpleNamespace(
        list_lesson_cards=SimpleNamespace(execute=AsyncMock(return_value=[]))
    )
    app = _build_real_router_app(curriculum=curriculum)
    client = TestClient(app)

    r = client.get("/api/v2/admin/programs/prog-1/lesson-cards")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 0
    assert body["cards"] == []


def test_list_lesson_cards_returns_503_when_curriculum_unconfigured():
    app = _build_real_router_app(curriculum=None)
    client = TestClient(app)

    r = client.get("/api/v2/admin/programs/prog-1/lesson-cards")
    assert r.status_code == 503, r.text
