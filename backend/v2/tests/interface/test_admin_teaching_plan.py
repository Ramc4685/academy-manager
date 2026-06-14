"""Interface tests for admin read-only teaching-plan visibility."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    SessionGroups,
)
from backend.v2.interfaces.admin.deps import get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy import tenant_scope

ACADEMY_ID = "test-academy"
OCCURRENCE_ID = "occ-001"
SESSION_ID = "session-001"
TEMPLATE_SESSION_ID = "template-session-001"
SCHEDULED_COACH_ID = "coach-scheduled"
REPLACEMENT_COACH_ID = "coach-replacement"
PROGRAM_ID = "prog-001"


class _FakeGenerateTeachingPlan:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def build_session_groups(
        self,
        *,
        session_id: str,
        program_id: str | None,
    ) -> SessionGroups:
        self.calls.append({"session_id": session_id, "program_id": program_id})
        return SessionGroups(
            groups=[
                {
                    "level_id": "level-1",
                    "level_name": "Grip and Control",
                    "level_sequence": 1,
                    "youtube_links": [],
                    "lesson_card": None,
                    "students": [
                        {
                            "student_id": "student-1",
                            "student_name": "Alice",
                            "next_skill": None,
                            "focus": "ready_for_level_up",
                        }
                    ],
                }
            ],
            unplaced=[],
        )


def _curriculum() -> SimpleNamespace:
    program = SimpleNamespace(
        program_id=PROGRAM_ID,
        name="Badminton Skill Pathway",
        model_dump=lambda: {"program_id": PROGRAM_ID, "name": "Badminton Skill Pathway"},
    )
    return SimpleNamespace(
        resolve_default_program=SimpleNamespace(execute=AsyncMock(return_value=program)),
        get_program=SimpleNamespace(execute=AsyncMock(return_value=program)),
    )


def _build_app(
    *,
    persona: str = "admin",
    occurrence_exists: bool = True,
    template_session_id: str | None = None,
) -> FastAPI:
    teaching_plan = _FakeGenerateTeachingPlan()

    async def get_occurrence(occurrence_id: str):
        if not occurrence_exists or occurrence_id != OCCURRENCE_ID:
            return None
        return SimpleNamespace(
            occurrence_id=OCCURRENCE_ID,
            session_id=SESSION_ID,
            template_session_id=template_session_id,
            scheduled_coach_id=SCHEDULED_COACH_ID,
            actual_coach_id=REPLACEMENT_COACH_ID,
            substitute_coach_id=None,
            start_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
        )

    use_cases = SimpleNamespace(
        generate_daily_teaching_plan=teaching_plan,
        get_session_occurrence=get_occurrence,
        curriculum=_curriculum(),
    )

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=f"{persona}-001",
        email=f"{persona}@example.com",
        academy_id=ACADEMY_ID,
        roles=(persona,),
    )
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases

    @app.middleware("http")
    async def _tenant_ctx(request: Request, call_next):
        with tenant_scope(ACADEMY_ID):
            return await call_next(request)

    app.state.teaching_plan = teaching_plan
    return app


def test_admin_occurrence_teaching_plan_returns_coach_plan_shape() -> None:
    app = _build_app()
    client = TestClient(app)

    response = client.get(
        f"/api/v2/admin/sessions/{OCCURRENCE_ID}/teaching-plan?program_id={PROGRAM_ID}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == SESSION_ID
    assert body["occurrence_id"] == OCCURRENCE_ID
    assert body["coach_id"] == REPLACEMENT_COACH_ID
    assert body["pathway_configured"] is True
    assert body["program_id"] == PROGRAM_ID
    assert body["groups"][0]["students"][0]["student_id"] == "student-1"
    assert app.state.teaching_plan.calls == [{"session_id": SESSION_ID, "program_id": PROGRAM_ID}]


def test_admin_occurrence_teaching_plan_uses_template_session_for_roster_plan() -> None:
    app = _build_app(template_session_id=TEMPLATE_SESSION_ID)
    client = TestClient(app)

    response = client.get(
        f"/api/v2/admin/sessions/{OCCURRENCE_ID}/teaching-plan?program_id={PROGRAM_ID}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["occurrence_id"] == OCCURRENCE_ID
    assert body["session_id"] == TEMPLATE_SESSION_ID
    assert app.state.teaching_plan.calls == [
        {"session_id": TEMPLATE_SESSION_ID, "program_id": PROGRAM_ID}
    ]


def test_admin_occurrence_teaching_plan_unknown_occurrence_returns_404() -> None:
    client = TestClient(_build_app(occurrence_exists=False))

    response = client.get(f"/api/v2/admin/sessions/{OCCURRENCE_ID}/teaching-plan")

    assert response.status_code == 404, response.text


def test_admin_occurrence_teaching_plan_wrong_persona_returns_404() -> None:
    client = TestClient(_build_app(persona="coach"))

    response = client.get(f"/api/v2/admin/sessions/{OCCURRENCE_ID}/teaching-plan")

    assert response.status_code == 404, response.text
