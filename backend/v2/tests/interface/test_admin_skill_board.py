"""Interface tests for the admin session skill-board route.

Standalone mini FastAPI app with fake in-memory repos.
No Mongo, no real auth.

Routes covered:
- GET /api/v2/admin/sessions/{session_id}/skill-board
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
)
from backend.v2.contexts.student_progress.domain.models import StudentLevelProgress
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy import tenant_scope

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACADEMY_ID = "test-academy"
SESSION_ID = "session-001"
PROGRAM_ID = "prog-001"
LEVEL_ID = "level-001"
SKILL_ID = "skill-001"

# ---------------------------------------------------------------------------
# Fake repos for GetSkillBoard
# ---------------------------------------------------------------------------


class _FakeLevelProgressRepo:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepo:
    async def list_for_students(self, student_ids: list[str], level_id: str) -> list[object]:
        return []


class _FakeRecommendationRepo:
    async def get_active_for_student(self, student_id: str, program_id: str) -> object | None:
        return None


class _FakeSkillLookup:
    def __init__(self) -> None:
        self._levels = {
            LEVEL_ID: SimpleNamespace(level_id=LEVEL_ID, name="Level 1", sequence=1),
        }
        self._skills = {
            LEVEL_ID: [
                SimpleNamespace(skill_id=SKILL_ID, name="Skill 001", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_app(*, admin_persona: bool = True) -> FastAPI:
    now = datetime.now(UTC)
    active_level = StudentLevelProgress(
        progress_id="lp-001",
        academy_id=ACADEMY_ID,
        student_id="stu-1",
        program_id=PROGRAM_ID,
        level_id=LEVEL_ID,
        status="active",
        started_at=now,
        created_at=now,
    )

    get_skill_board = GetSkillBoard(
        level_progress=_FakeLevelProgressRepo([active_level]),  # type: ignore[arg-type]
        skill_progress=_FakeSkillProgressRepo(),  # type: ignore[arg-type]
        recommendations=_FakeRecommendationRepo(),  # type: ignore[arg-type]
        skill_lookup=_FakeSkillLookup(),  # type: ignore[arg-type]
    )

    student_progress = SimpleNamespace(
        get_skill_board=get_skill_board,
    )

    curriculum = SimpleNamespace(
        get_program=SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    program_id=PROGRAM_ID,
                    name="Badminton Skill Pathway",
                    model_dump=lambda: {
                        "program_id": PROGRAM_ID,
                        "name": "Badminton Skill Pathway",
                    },
                )
            )
        ),
        resolve_default_program=SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(program_id=PROGRAM_ID, name="Badminton Skill Pathway")
            )
        ),
        list_levels=SimpleNamespace(execute=AsyncMock(return_value=[])),
    )

    async def list_admin_enrollments_for_session(session_id: str) -> list[dict[str, object]]:
        return [
            {"student_id": "stu-1", "full_name": "Netra M"},
            {"student_id": "stu-2", "full_name": "Jaya J"},
        ]

    # Build a minimal AdminUseCases via SimpleNamespace override
    # (AdminUseCases is a large dataclass; use dependency override to avoid
    # constructing every required field)
    use_cases = SimpleNamespace(
        student_progress=student_progress,
        curriculum=curriculum,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_admin_students=AsyncMock(),
        get_admin_student=None,
    )

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")

    if admin_persona:
        app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
            user_id="admin-001",
            email="admin@example.com",
            academy_id=ACADEMY_ID,
            roles=("admin",),
        )
    else:
        # Wrong persona: coach
        app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
            user_id="coach-001",
            email="coach@example.com",
            academy_id=ACADEMY_ID,
            roles=("coach",),
        )

    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(ACADEMY_ID):
            return await call_next(request)

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_build_app(admin_persona=True))


@pytest.fixture()
def client_coach_persona() -> TestClient:
    return TestClient(_build_app(admin_persona=False))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_admin_session_skill_board_returns_groups(client: TestClient) -> None:
    response = client.get(
        f"/api/v2/admin/sessions/{SESSION_ID}/skill-board?program_id={PROGRAM_ID}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["program_name"] == "Badminton Skill Pathway"
    assert body["groups"][0]["students"][0]["student_id"] == "stu-1"


def test_admin_session_skill_board_includes_unplaced(client: TestClient) -> None:
    response = client.get(
        f"/api/v2/admin/sessions/{SESSION_ID}/skill-board?program_id={PROGRAM_ID}"
    )
    body = response.json()
    assert [u["student_id"] for u in body["unplaced"]] == ["stu-2"]


def test_admin_session_skill_board_wrong_persona(client_coach_persona: TestClient) -> None:
    response = client_coach_persona.get(f"/api/v2/admin/sessions/{SESSION_ID}/skill-board")
    assert response.status_code in (401, 403, 404)
