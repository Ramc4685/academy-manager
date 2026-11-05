"""``POST /coach/students/{id}/technique-observation-draft`` (B6): same
coverage guard as the skill-note routes, draft returned and nothing stored."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.domain.errors import AiDisabled, AiNotEntitled
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

STUDENT, OTHER_STUDENT, SESSION, COACH = "stu-1", "stu-2", "sess-1", "coach-1"
ROUTE = f"/api/v2/coach/students/{STUDENT}/technique-observation-draft"
STATUS_ROUTE = "/api/v2/coach/ai/status"
SUGGESTION = {
    "criterion_id": "c-1",
    "skill_id": "sk-grip",
    "skill_name": "Forehand grip",
    "parent_sentence": "Maya is holding the racket with a flat thumb now.",
    "coach_summary": "Flat thumb on forehand grip.",
}


class SpyDraft:
    def __init__(self, outcome: Any = None) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return SimpleNamespace(model_dump=lambda: dict(SUGGESTION))


class AssignedSessions:
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return coach_id == COACH and session_id == SESSION


def _client(
    roles: tuple[str, ...], draft: SpyDraft, user_id: str = COACH, *, enabled: bool = False
) -> TestClient:
    async def enrollments(student_id: str) -> list[Any]:
        return [SimpleNamespace(session_id=SESSION)] if student_id == STUDENT else []

    use_cases = object.__new__(CoachUseCases)
    use_cases.assigned_sessions = AssignedSessions()
    use_cases.get_active_session_enrollments_for_student = enrollments
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.state.ai_technique = SimpleNamespace(draft_for_student=draft, enabled=enabled)
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=user_id,
        email="x@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_assigned_coach_gets_the_draft_with_the_coach_as_approver() -> None:
    draft = SpyDraft()
    response = _client(("coach",), draft).post(ROUTE, json={"observation": "flat thumb today"})
    assert response.status_code == 200, response.text
    assert response.json() == SUGGESTION
    assert draft.calls == [
        {"student_id": STUDENT, "observation": "flat thumb today", "approver": COACH}
    ]


def test_admin_without_coach_role_is_404() -> None:
    draft = SpyDraft()
    response = _client(("admin",), draft, user_id="u-admin").post(
        ROUTE, json={"observation": "flat thumb today"}
    )
    assert response.status_code == 404 and draft.calls == []


def test_foreign_student_is_404_before_any_model_call() -> None:
    draft = SpyDraft()
    client = _client(("coach",), draft)
    other = f"/api/v2/coach/students/{OTHER_STUDENT}/technique-observation-draft"
    assert client.post(other, json={"observation": "flat thumb today"}).status_code == 404
    assert draft.calls == []


def test_unassigned_coach_is_404() -> None:
    draft = SpyDraft()
    response = _client(("coach",), draft, user_id="coach-other").post(
        ROUTE, json={"observation": "flat thumb today"}
    )
    assert response.status_code == 404 and draft.calls == []


def test_observation_is_text_only_and_bounded() -> None:
    client = _client(("coach",), SpyDraft())
    assert client.post(ROUTE, json={"observation": ""}).status_code == 422
    assert client.post(ROUTE, json={"observation": "x" * 501}).status_code == 422
    assert client.post(ROUTE, json={"audio": "base64..."}).status_code == 422


def test_ai_errors_pass_through_with_their_codes() -> None:
    disabled = _client(("coach",), SpyDraft(AiDisabled("off"))).post(
        ROUTE, json={"observation": "flat thumb"}
    )
    assert disabled.status_code == 503 and disabled.json()["error"]["code"] == "Ai.Disabled"
    gated = _client(("coach",), SpyDraft(AiNotEntitled("plan"))).post(
        ROUTE, json={"observation": "flat thumb"}
    )
    assert gated.status_code == 403 and gated.json()["error"]["code"] == "Ai.NotEntitled"


def test_coach_only_persona_reads_the_ai_status() -> None:
    assert _client(("coach",), SpyDraft(), enabled=True).get(STATUS_ROUTE).json() == {
        "enabled": True
    }
    assert _client(("coach",), SpyDraft()).get(STATUS_ROUTE).json() == {"enabled": False}
    assert _client(("parent",), SpyDraft(), user_id="u-parent").get(STATUS_ROUTE).status_code == 404
